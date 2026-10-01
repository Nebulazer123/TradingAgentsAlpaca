"""Read-only typed queries over authenticated retained benchmark material.

The source-bundle reader authenticates originals before dispatch. These pure
operators receive no gold, filesystem paths to open, tools or execution authority.
Unsupported and ambiguous financial material remains explicitly unavailable.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from decimal import Decimal, InvalidOperation, localcontext

from lxml import etree

from tradingagents.dataflows.pit.official_observations import _normalize_source_value, _select_json
from tradingagents.research.qualification_media import _attrs, _node_text, _numeric

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared compatibility dependency.
    import tomli as tomllib

SCHEMA = 'research_semantic_query/v1'
BUNDLE_SCHEMA = 'research_semantic_source_bundle/v2'
X = 'http://www.xbrl.org/2003/instance'
INLINE_NAMESPACES = {'http://www.xbrl.org/2008/inlineXBRL', 'http://www.xbrl.org/2013/inlineXBRL'}
NS = {'x': X}


class SemanticInputError(ValueError):
    pass


def exact_fields(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise SemanticInputError(f'{label} has noncanonical fields')
    return value


def timestamp(value):
    if type(value) is not str:
        raise SemanticInputError('Timestamp is not text')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise SemanticInputError('Invalid timestamp') from exc
    if parsed.tzinfo is None:
        raise SemanticInputError('Timestamp has no offset')
    return parsed.astimezone(dt.timezone.utc)


def markup(value, root_name):
    if type(value) is not str or len(value) > 1_000_000:
        raise SemanticInputError('Markup is missing or exceeds bounds')
    if '<!DOCTYPE' in value.upper() or '<!ENTITY' in value.upper():
        raise SemanticInputError('External declarations are unavailable')
    try:
        node = etree.fromstring(value.encode(), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise SemanticInputError('Invalid context/unit markup') from exc
    if node.tag != '{' + X + '}' + root_name:
        raise SemanticInputError('Wrong context/unit namespace')
    return node


def qname(value, namespaces):
    if type(value) is not str or not value or value.count(':') > 1:
        raise SemanticInputError('Invalid financial QName')
    prefix, sep, name = value.partition(':')
    uri = namespaces.get(prefix if sep else '')
    if type(uri) is not str or not uri:
        raise SemanticInputError('Unbound financial QName')
    return '{' + uri + '}' + (name if sep else prefix)


def node_qname(node):
    return qname(node.text, {'' if k is None else k: v for k, v in node.nsmap.items()})


def decimal(value):
    if type(value) is not str or len(value) > 8192 or not re.fullmatch(r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)', value):
        raise SemanticInputError('Financial value is not an exact decimal lexeme')
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise SemanticInputError('Invalid financial value') from exc
    if not parsed.is_finite():
        raise SemanticInputError('Nonfinite financial value')
    return parsed


def normalized(value):
    with localcontext() as context:
        context.prec = 4096
        text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return '0' if value == 0 else text


def selector(value):
    exact_fields(value, {'concept_family', 'concept_local_name', 'entity', 'period', 'unit', 'dimensions'}, 'financial selector')
    if value['dimensions'] != 'none':
        raise SemanticInputError('Only explicitly undimensioned facts are supported')
    if type(value['concept_family']) is not str or not value['concept_family']:
        raise SemanticInputError('Concept family is missing')
    if type(value['concept_local_name']) is not str or not re.fullmatch(r'[A-Za-z_][\w.-]*', value['concept_local_name']):
        raise SemanticInputError('Concept name is invalid')
    if type(value['entity']) is not list or len(value['entity']) != 2 or any(type(v) is not str or not v for v in value['entity']):
        raise SemanticInputError('Entity is invalid')
    period = value['period']
    if type(period) is not list or len(period) not in {1, 2} or any(type(p) is not list or len(p) != 2 for p in period):
        raise SemanticInputError('Full period is invalid')
    if [p[0] for p in period] not in [['instant'], ['startDate', 'endDate']]:
        raise SemanticInputError('Full period is invalid')
    for _, date in period:
        if type(date) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
            raise SemanticInputError('Period date is invalid')
        try:
            dt.date.fromisoformat(date)
        except ValueError as exc:
            raise SemanticInputError('Invalid period date') from exc
    if len(period) == 2 and period[0][1] > period[1][1]:
        raise SemanticInputError('Reporting period is reversed')
    units = value['unit']
    if type(units) is not list or len(units) != 2 or any(type(g) is not list or any(type(u) is not str or not u.startswith('{') or '}' not in u for u in g) for g in units):
        raise SemanticInputError('Units are invalid')
    if not units[0] or any(g != sorted(set(g)) for g in units):
        raise SemanticInputError('Units are not canonical')
    return value


def selected_fact(source, wanted):
    extracted = source.get('extraction')
    if type(extracted) is not dict or extracted.get('schema_version') not in {'research_media_source/v1', 'research_media_source/v2'} or extracted.get('format') != 'html':
        raise SemanticInputError('Financial source is not genuine extracted HTML')
    material = extracted.get('material')
    if type(material) is not dict or any(type(material.get(k)) is not dict for k in ('inline_facts', 'contexts', 'units')):
        raise SemanticInputError('Financial material is incomplete')
    found = []
    for fact in material['inline_facts'].values():
        if type(fact) is not dict or fact.get('kind') != 'nonfraction':
            continue
        attrs, namespaces = fact.get('attributes'), fact.get('namespaces')
        if type(attrs) is not dict or type(namespaces) is not dict:
            raise SemanticInputError('Financial fact metadata is invalid')
        if any(type(k) is not str or type(v) is not str for k, v in namespaces.items()) or any(k in attrs and type(attrs[k]) is not str for k in ('name', 'contextref', 'unitref', 'decimals', 'scale', 'sign', 'format', 'nil')):
            raise SemanticInputError('Financial fact attribute types are invalid')
        concept = qname(attrs.get('name'), namespaces)
        uri, name = concept[1:].split('}', 1)
        family = 'us-gaap' if re.fullmatch(r'https?://(?:xbrl\.)?fasb\.org/us-gaap/\d{4}(?:-\d{2}-\d{2})?', uri) else '{' + uri + '}'
        if name != wanted['concept_local_name'] or family != wanted['concept_family']:
            continue
        original_markup = fact.get('markup')
        if type(original_markup) is not str or len(original_markup) > 1_000_000 or '<!DOCTYPE' in original_markup.upper() or '<!ENTITY' in original_markup.upper():
            raise SemanticInputError('Financial fact markup is missing or unsafe')
        try:
            original_fact = etree.fromstring(original_markup.encode(), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
        except etree.XMLSyntaxError as exc:
            raise SemanticInputError('Financial fact markup is invalid') from exc
        tag = etree.QName(original_fact)
        if tag.namespace not in INLINE_NAMESPACES or tag.localname != 'nonFraction':
            raise SemanticInputError('Financial fact namespace is invalid')
        original_attrs = _attrs(original_fact)
        if original_attrs != attrs:
            raise SemanticInputError('Extracted fact metadata differs from retained markup')
        if type(fact.get('text')) is not str:
            raise SemanticInputError('Financial fact text is missing')
        original_namespaces = {'' if k is None else k: v for k, v in original_fact.nsmap.items()}
        if qname(original_attrs['name'], original_namespaces) != concept:
            raise SemanticInputError('Financial concept differs from retained markup')
        original_text, continuation_ids = _node_text(original_fact), []
        next_id = original_attrs.get('continuedat')
        while next_id:
            if next_id in continuation_ids or len(continuation_ids) >= 256:
                raise SemanticInputError('Financial continuation is cyclic or exceeds bounds')
            continuation_ids.append(next_id)
            continuations = material.get('continuations')
            record = continuations.get(next_id) if type(continuations) is dict else None
            continuation_markup = record.get('markup') if type(record) is dict else None
            if type(continuation_markup) is not str or len(continuation_markup) > 1_000_000 or '<!DOCTYPE' in continuation_markup.upper() or '<!ENTITY' in continuation_markup.upper():
                raise SemanticInputError('Financial continuation markup is missing or unsafe')
            try:
                continued = etree.fromstring(continuation_markup.encode(), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
            except etree.XMLSyntaxError as exc:
                raise SemanticInputError('Financial continuation markup is invalid') from exc
            tag = etree.QName(continued)
            if tag.namespace not in INLINE_NAMESPACES or tag.localname != 'continuation' or continued.get('id') != next_id:
                raise SemanticInputError('Financial continuation identity is invalid')
            original_text += _node_text(continued)
            next_id = _attrs(continued).get('continuedat')
        if original_text != fact['text'] or continuation_ids != fact.get('continuation_ids'):
            raise SemanticInputError('Financial fact text differs from retained markup')
        numeric_value, numeric_status = _numeric(original_text, original_attrs, {None if k == '' else k: v for k, v in original_namespaces.items()})
        if numeric_status != 'available' or numeric_value != fact.get('value'):
            raise SemanticInputError('Financial fact value differs from the bound transformation')
        decimals = attrs.get('decimals')
        if decimals is not None and decimals != 'INF' and (not re.fullmatch(r'-?\d{1,4}', decimals) or abs(int(decimals)) > 4096):
            raise SemanticInputError('Reporting precision exceeds bounded support')
        try:
            context = markup(material['contexts'][attrs['contextref']]['markup'], 'context')
            unit = markup(material['units'][attrs['unitref']]['markup'], 'unit')
        except (KeyError, TypeError) as exc:
            raise SemanticInputError('Financial context/unit is missing') from exc
        if context.get('id') != attrs['contextref'] or unit.get('id') != attrs['unitref']:
            raise SemanticInputError('Context/unit identity mismatch')
        if context.find('x:entity/x:segment', NS) is not None or context.find('x:scenario', NS) is not None:
            continue
        entities = context.findall('x:entity/x:identifier', NS)
        periods = context.findall('x:period', NS)
        if len(entities) != 1 or len(periods) != 1:
            raise SemanticInputError('Context has ambiguous entity/period')
        entity = [entities[0].get('scheme'), entities[0].text]
        period = [[etree.QName(n).localname, n.text] for n in periods[0]]
        divide = unit.find('x:divide', NS)
        if divide is None:
            if not len(unit) or any(child.tag != '{' + X + '}measure' for child in unit):
                raise SemanticInputError('Unit has unsupported children')
        else:
            if len(unit) != 1 or len(divide) != 2 or [child.tag for child in divide] != ['{' + X + '}unitNumerator', '{' + X + '}unitDenominator'] or any(not len(child) or any(n.tag != '{' + X + '}measure' for n in child) for child in divide):
                raise SemanticInputError('Divided unit structure is invalid')
        measures = [sorted(node_qname(n) for n in unit.findall('x:measure', NS)), []] if divide is None else [
            sorted(node_qname(n) for n in divide.findall('x:unitNumerator/x:measure', NS)),
            sorted(node_qname(n) for n in divide.findall('x:unitDenominator/x:measure', NS))]
        if entity != wanted['entity'] or period != wanted['period'] or measures != wanted['unit']:
            continue
        if fact.get('status') != 'available' or attrs.get('nil') in {'true', '1'}:
            raise SemanticInputError('Selected fact is unavailable')
        if attrs.get('sign') not in {None, '+', '-'}:
            raise SemanticInputError('Invalid fact sign')
        found.append({'value': decimal(fact.get('value')), 'decimals': attrs.get('decimals'),
                      'period': period, 'unit': measures, 'concept': concept})
    if not found:
        raise SemanticInputError('No fact matches the full financial selector')
    # Duplicate representations are acceptable only when all compared fields
    # agree. Conflicting matching facts never silently select the first one.
    if any(row != found[0] for row in found[1:]):
        raise SemanticInputError('Matching financial facts conflict')
    return found[0]


def workflow_configuration(material, phase, focus_automation_id):
    if type(focus_automation_id) is not str:
        raise SemanticInputError('Focused workflow role is invalid')
    if type(material) is not dict or material.get('schema') != 'counterfactual_workflow_configuration_input/v2' or material.get('fixture_not_deployed_configuration') is not True:
        raise SemanticInputError('Workflow source is not the declared fixture contract')
    contract, roles, tomls = (material.get(k) for k in ('schedule_contract', 'role_contract', 'automation_tomls'))
    if not all(type(v) is dict for v in (contract, roles, tomls)):
        raise SemanticInputError('Workflow material is incomplete')
    expected = contract.get('automations')
    policy = contract.get('deployment_policy')
    if type(policy) is not dict:
        raise SemanticInputError('Workflow deployment policy is invalid')
    phases = policy.get('deployment_phases')
    assignments = roles.get('automations')
    if type(expected) is not dict or type(phases) is not dict or type(assignments) is not dict or type(phase) is not str or phase not in {'predeployment_paused', 'frozen_observer'} or phase not in phases:
        raise SemanticInputError('Workflow contract/phase is invalid')
    phase_data = phases[phase]
    if type(phase_data) is not dict or type(phase_data.get('active_automation_ids')) is not list or type(phase_data.get('paused_automation_ids')) is not list:
        raise SemanticInputError('Workflow phase IDs are invalid')
    for field in ('active_automation_ids', 'paused_automation_ids'):
        values = phase_data[field]
        if any(type(v) is not str or not v for v in values) or len(set(values)) != len(values):
            raise SemanticInputError('Workflow phase IDs contain invalid or duplicate roles')
    active, paused = (set(phase_data[k]) for k in ('active_automation_ids', 'paused_automation_ids'))
    if focus_automation_id not in expected:
        raise SemanticInputError('Focused workflow role is missing from its contract')
    conforms = len(expected) == 10 and set(tomls) == set(expected) and active | paused == set(expected) and not active & paused
    row_results = {}
    for aid, expected_row in expected.items():
        if type(expected_row) is not dict or type(tomls.get(aid)) is not str:
            row_results[aid] = False
            continue
        try:
            actual = tomllib.loads(tomls[aid])
        except tomllib.TOMLDecodeError:
            row_results[aid] = False
            continue
        row_conforms = actual.get('id') == aid and actual.get('kind') == 'cron' and type(actual.get('version')) is int and actual['version'] == 1
        row_conforms &= actual.get('status') == ('ACTIVE' if aid in active else 'PAUSED')
        row_conforms &= assignments.get(aid) == expected_row.get('role')
        for field in ('name', 'target', 'cwds', 'execution_environment', 'rrule', 'model', 'reasoning_effort', 'notification_policy'):
            row_conforms &= field in expected_row and actual.get(field) == expected_row.get(field)
        prompt = actual.get('prompt')
        if type(prompt) is not str:
            row_results[aid] = False
            continue
        required, forbidden = expected_row.get('required_prompt_phrases'), expected_row.get('forbidden_prompt_phrases')
        if type(required) is not list or type(forbidden) is not list or any(type(p) is not str for p in [*required, *forbidden]):
            raise SemanticInputError('Workflow prompt requirements are invalid')
        row_conforms &= hashlib.sha256(prompt.encode()).hexdigest() == expected_row.get('prompt_sha256')
        row_conforms &= all(p in prompt for p in required) and all(p not in prompt for p in forbidden)
        row_results[aid] = bool(row_conforms)
    return {'configuration_conforms': bool(conforms and all(row_results.values())),
            'focus_role_conforms': row_results[focus_automation_id], 'deployment_proven': False,
            'evaluation_grants_submission_authority': False}


def validate_semantic_query(query):
    """Validate query syntax without reading a source or receiving an answer."""
    if type(query) is not dict or query.get('schema_version') != SCHEMA:
        raise SemanticInputError('Unsupported semantic query version')
    operator = query.get('operator')
    if type(operator) is not str:
        raise SemanticInputError('Semantic operator is invalid')
    fields = {
        'scalar_path': {'source_id', 'json_path'},
        'workflow_configuration_conformance': {'source_id', 'deployment_phase', 'focus_automation_id'},
        'select_full_period_fact': {'source_ids', 'selector'},
        'compare_cross_filing_precision': {'source_ids', 'selector'},
        'prospective_capture_cutoff': {'source_id', 'cutoff'},
    }
    if operator not in fields:
        raise SemanticInputError('Unknown semantic operator')
    exact_fields(query, {'schema_version', 'operator', *fields[operator]}, 'semantic query')
    if 'source_id' in query and (type(query['source_id']) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', query['source_id'])):
        raise SemanticInputError('Semantic source ID is invalid')
    if operator in {'select_full_period_fact', 'compare_cross_filing_precision'}:
        selector(query['selector'])
        ids = query['source_ids']
        length = 1 if operator == 'select_full_period_fact' else 2
        if type(ids) is not list or len(ids) != length or any(type(i) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', i) for i in ids) or len(set(ids)) != len(ids):
            raise SemanticInputError('Financial source IDs are invalid')
    elif operator == 'scalar_path':
        path = query['json_path']
        if type(path) is not list or not 1 <= len(path) <= 32 or any(type(p) not in {str, int} or (type(p) is int and p < 0) or (type(p) is str and (not p or len(p) > 256)) for p in path):
            raise SemanticInputError('Scalar path is invalid')
    elif operator == 'workflow_configuration_conformance':
        if type(query['deployment_phase']) is not str or query['deployment_phase'] not in {'predeployment_paused', 'frozen_observer'}:
            raise SemanticInputError('Workflow phase is invalid')
        if type(query['focus_automation_id']) is not str or not re.fullmatch(r'tradingagents-[a-z0-9-]{1,100}', query['focus_automation_id']):
            raise SemanticInputError('Focused workflow role is invalid')
    elif operator == 'prospective_capture_cutoff':
        timestamp(query['cutoff'])
    return dict(query)


def evaluate(query, bundle):
    query = validate_semantic_query(query)
    exact_fields(bundle, {'schema_version', 'sources'}, 'source bundle')
    if bundle['schema_version'] != BUNDLE_SCHEMA or type(bundle['sources']) is not list or not 1 <= len(bundle['sources']) <= 10:
        raise SemanticInputError('Unsupported source bundle')
    sources = {}
    for source in bundle['sources']:
        if type(source) is not dict or type(source.get('source_id')) is not str or not source['source_id'] or source['source_id'] in sources:
            raise SemanticInputError('Source IDs are invalid or duplicated')
        if 'media' in source:
            exact_fields(source, {'source_id', 'media'}, 'media source')
            media = source['media']
            if type(media) is not dict or media.get('schema_version') not in {'research_media_source/v1', 'research_media_source/v2'} or type(media.get('material')) is not dict:
                raise SemanticInputError('Media source is incomplete')
        elif 'extraction' in source:
            exact_fields(source, {'source_id', 'accession', 'extraction', 'capture_record', 'publication_record', 'publication_capture_record'}, 'financial source')
            extraction = source['extraction']
            capture = source['capture_record']
            publication_capture = source['publication_capture_record']
            if type(extraction) is not dict or type(capture) is not dict or type(publication_capture) is not dict:
                raise SemanticInputError('Financial source custody is incomplete')
            if extraction.get('schema_version') not in {'research_media_source/v1', 'research_media_source/v2'} or extraction.get('format') != 'html' or extraction.get('page_number') is not None or type(extraction.get('material')) is not dict:
                raise SemanticInputError('Financial source extraction is invalid')
            exact_fields(source['publication_record'], {'accessionNumber', 'acceptanceDateTime', 'filingDate', 'reportDate', 'form'}, 'publication record')
            if source['accession'] != source['publication_record']['accessionNumber']:
                raise SemanticInputError('Publication belongs to a different accession')
            if type(extraction.get('original_sha256')) is not str or not re.fullmatch(r'[0-9a-f]{64}', extraction['original_sha256']) or capture.get('body_sha256') != extraction['original_sha256']:
                raise SemanticInputError('Financial capture is bound to a different original')
            for receipt in (capture, publication_capture):
                if receipt.get('schema') != 'prospective-readonly-source-response/v1' or receipt.get('analysis_only') is not True or receipt.get('can_submit_orders') is not False or receipt.get('execution_authority') != 'none':
                    raise SemanticInputError('Financial custody receipt has invalid authority/schema')
                if type(receipt.get('body_sha256')) is not str or not re.fullmatch(r'[0-9a-f]{64}', receipt['body_sha256']):
                    raise SemanticInputError('Financial custody receipt has no original identity')
                timestamp(receipt.get('captured_at'))
        else:
            exact_fields(source, {'source_id', 'material'}, 'workflow source')
        sources[source['source_id']] = source
    operator = query.get('operator')
    if operator == 'scalar_path':
        if query['source_id'] not in sources or 'media' not in sources[query['source_id']]:
            raise SemanticInputError('Scalar source is missing')
        try:
            value = _select_json(sources[query['source_id']]['media'], tuple(query['json_path']), label='benchmark scalar field')
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SemanticInputError('Scalar field is unavailable') from exc
        if type(value) is Decimal:
            return _normalize_source_value(value)
        if type(value) not in {str, int, float}:
            raise SemanticInputError('Selected field is not scalar')
        if type(value) is float and not math.isfinite(value):
            raise SemanticInputError('Selected field is not finite')
        return str(value)
    if operator == 'workflow_configuration_conformance':
        if type(query['source_id']) is not str or query['source_id'] not in sources:
            raise SemanticInputError('Workflow source is missing')
        return workflow_configuration(sources[query['source_id']].get('material'), query['deployment_phase'], query['focus_automation_id'])
    if operator in {'select_full_period_fact', 'compare_cross_filing_precision'}:
        exact_fields(query, {'schema_version', 'operator', 'source_ids', 'selector'}, 'financial query')
        wanted = selector(query['selector'])
        ids = query['source_ids']
        expected_length = 1 if operator == 'select_full_period_fact' else 2
        if type(ids) is not list or len(ids) != expected_length or any(type(i) is not str or i not in sources for i in ids) or len(set(ids)) != len(ids):
            raise SemanticInputError('Financial source IDs are invalid')
        facts = [selected_fact(sources[i], wanted) for i in ids]
        if operator == 'select_full_period_fact':
            return {'value': normalized(facts[0]['value']), 'period': facts[0]['period'], 'unit': facts[0]['unit']}
        accessions = [sources[i].get('accession') for i in ids]
        if any(type(a) is not str or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', a) for a in accessions) or accessions[0] == accessions[1]:
            raise SemanticInputError('Comparison needs distinct filing accessions')
        if facts[0]['concept'] != facts[1]['concept'] and wanted['concept_family'] != 'us-gaap':
            raise SemanticInputError('Cross-namespace equivalence is not established')
        a, b = facts
        compatible = False
        if a['value'] != b['value'] and all(type(f['decimals']) is str and (f['decimals'] == 'INF' or re.fullmatch(r'-?\d+', f['decimals'])) for f in facts):
            with localcontext() as context:
                context.prec = max(4096, len(str(a['value'])) + len(str(b['value'])) + 8192 + 32)
                radii = [Decimal(0) if f['decimals'] == 'INF' else Decimal(5).scaleb(-int(f['decimals']) - 1) for f in facts]
                compatible = abs(a['value'] - b['value']) <= sum(radii)
        classification = 'consistent_value' if a['value'] == b['value'] else ('compatible_reporting_precision' if compatible else 'unresolved_value_conflict')
        return {'classification': classification, 'values': [normalized(f['value']) for f in facts],
                'accessions': accessions, 'restatement_established': False}
    if operator == 'prospective_capture_cutoff':
        exact_fields(query, {'schema_version', 'operator', 'source_id', 'cutoff'}, 'cutoff query')
        if type(query['source_id']) is not str or query['source_id'] not in sources:
            raise SemanticInputError('Cutoff source is missing')
        source = sources[query['source_id']]
        cutoff = timestamp(query['cutoff'])
        captured_text = source.get('capture_record', {}).get('captured_at')
        captured = timestamp(captured_text)
        publication = timestamp(source.get('publication_record', {}).get('acceptanceDateTime'))
        metadata_observed = timestamp(source.get('publication_capture_record', {}).get('captured_at'))
        if publication > captured:
            raise SemanticInputError('Publication occurs after the alleged filing capture')
        eligible = captured <= cutoff and publication <= cutoff and metadata_observed <= cutoff
        return {'eligible_for_this_prospective_cut': eligible,
                'reason': 'source_observed_after_cutoff' if captured > cutoff else ('source_published_after_cutoff' if publication > cutoff else ('publication_metadata_observed_after_cutoff' if metadata_observed > cutoff else 'source_observed_and_published_before_cutoff')),
                'published_before_cutoff': publication <= cutoff, 'actual_capture': captured_text}
    raise SemanticInputError('Unknown semantic operator')
