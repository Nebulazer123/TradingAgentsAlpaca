# Reading real documents for qualification

The benchmark now accepts retained web pages, tables, inline financial facts,
PDF pages, PNG/JPEG images, UTF-8 repository documents and saved tool responses.
It does not consult an answer key to extract a document. Existing v4 registrations
still replay through their original JSON-byte-span path.

Single-original media registrations use `research_qualification_registration/v5` and a
`research_media_input/v1` descriptor, or v2 for a locked HTML element selection.
Each case binds the complete original
artifact hash, actual extraction-engine versions and the resulting extraction
hash. PDF page numbers are checked against the real PDF page count. An image is
one page. HTML spans and page-break style cues cannot claim native page counts.

An HTML selection lists actual element IDs before execution. It includes the
selected markup and financial facts, plus their referenced contexts, units and
continuations. The original whole-document hash remains bound. Every source lane
sees this same selected material; a missing or changed selection rejects replay.
Whole-document v1 inputs remain supported. Selection avoids sending an entire
large filing for a question about one passage.

Every source lane receives the same extracted `research_media_source/v1` or v2 bytes.
The paired no-text lane receives no document bytes. Answer labels remain in the
scoring registration and are excluded from adapter inputs. Source descriptors,
original hashes, page numbers and extraction transformations remain in receipts.

## Questions using several originals

The v6 registration adds `research_source_bundle_input/v1` and typed
`research_semantic_query/v1` questions. It preserves both v4 JSON-span and v5
single-original replay. The reader verifies every complete original, including
secondary filings, their actual collection receipts, SEC submission metadata
and that metadata's collection receipt. A bad secondary component stops the
comparison. Reader and interpreter source identities, all original spans and
the resulting extraction are bound before execution.

Financial questions select the complete reporting period, issuer, concept and
unit; apply the retained sign and scale; compare exact values within their stated
reporting precision; or test whether publication, filing collection and metadata
collection all preceded a prospective cutoff. A past publication date cannot
pretend that a later collection existed earlier. Conflicting matching facts
remain unavailable instead of silently selecting the first. Numeric fact text,
namespaces, attributes and continuations are checked against the retained markup.
Financial selectors currently require explicitly undimensioned facts.

Workflow questions check the named role and the complete ten-role configuration
against its declared phase. They read counterfactual TOMLs, never deploy them.
The fixture binds the original schedule and role contracts, audit source and
test source; its only contract transformation derives the fixture prompt hashes
from the original required phrases. Local custody paths and preparation questions
are excluded from compared material. The result always records that configuration
checking proves no deployment and grants no order-submission authority.

Ordinary page, repository and tool-output questions keep source-derived scalar
selection. Genuine PDF/image page identity depends on the original and intrinsic
page number; extra descriptor variants cannot count the same page twice. No gold
answer enters the reader or its operators. All compared lanes receive identical
canonical source bundles, and no-text twins receive no material.

## Material and locations

HTML extraction retains the original markup, tables and their DOM locations,
inline facts, genuine XBRL contexts and units, scales, signs and continuation
chains. Numeric values use exact decimal arithmetic. A counterfeit namespace,
missing context/unit, cyclic continuation or unsupported transformation cannot
silently produce an accepted financial value. XML comments and genuine
`ix:exclude` content do not participate in a fact's value; their source markup
remains visible.

The material includes XPath and source-line locations for HTML. These identify
nodes in the retained original; they are not claims of byte-exact node slices.
JSON selection uses the actual source-derived value. Repository and tool text
retain their original UTF-8 text and lines, including hostile instructions for
the injection checks.

PDF extraction retains native page numbers and word coordinates in PDF points.
A page without digital words is rendered at 150 DPI and read with OCR; the
render hash, OCR settings, pixel coordinates and confidence are recorded. Images
use the same local OCR route with original-image coordinates. No answer is
invented for a blank image.

PDF font controls forbidden in XML are escaped only while parsing and restored
exactly in word text. The intermediate layout hash and codepoint counts record
this transformation. The reader does not guess which punctuation a font intended.

Current bounded limitations are explicit: numeric transformation support is a
subset of the standard registries; formatted or escaped nonnumeric facts and
fractions require a supported explicit selection before becoming values. PDF
OCR currently handles pages without digital words, rather than locating every
image or chart embedded alongside digital text. Engine absence, changed versions
or extraction drift reject replay. Corpus questions must respect these limits;
they must not manufacture accuracy by reading a scoring label.

## Evidence to date

The affected media, benchmark, graph and price-source checks passed 157 tests.
They cover genuine XHTML and tolerant HTML, namespace impostors, financial
context/unit/scale/sign/continuations, exact decimals, real PDF pages and OCR,
source drift, label isolation, shared-source retrieval and preserved v4 replay.
These are code checks, not corpus qualification results.

The later HTML-selection gate passed 106 benchmark/media/graph/source-input tests.
The real-page sweep then exposed a PDF font-control parsing failure; its repair
passed all 35 media tests, including actual text OCR and the demonstrated font
failure. Passing evidence for unchanged official-price behavior is reused.

The corrected reader also processed all 81 retained SEC HTML originals without
network or model calls. All five tracked structural counts matched the earlier
inventory across every document: 143,296 numeric facts, 13,567 nonnumeric facts,
42,889 contexts, 697 units and 5,540 continuations. Of the facts, 145,425 had
extractable values; 9,720 needed a nonnumeric transform, 718 were nil, 475 used
an unsupported transform namespace and 525 used an unsupported transform.
These counts prove extraction coverage and explicit limitations, not semantic
accuracy. No HTML pages were counted.

Saved evidence lives under `results/readiness_continuation/` in
`20260930-media-review/` and `20260930-retained-html-review/`. The initial failed
namespace serialization check is preserved in `20260930-media-affected/`.
Source tests and inventories remain distinct from the registered case results
below.

The corpus preparation now retains HPE's 180-page and JPMorganChase's 364-page
publisher-original PDFs, with actual download times and custody receipts.
Five hundred distinct native pages have been extracted and bound. The original
187 successful preparations were reused after the font repair; the failed sweep
receipt remains preserved. Prepared pages live under
`results/readiness_continuation/20260930-pdf-page-repaired/`. Questions, labels and
qualification were then completed separately as described below; extraction
preparation itself is not a 500-case pass.

## Checked local corpus result — October 1

The v5 registration contains 500 native PDF pages, 300 temporal source questions,
400 repository workflow constraints and 200 controlled hostile-input derivatives.
Every original location and gold label was checked in a separate root self-review.
Answers remain outside extraction. Of 1,400 cases, 901 are critical, 280 high
severity and 219 normal. No arbitrary HTML span counts as a PDF page.

The deterministic source-derived JSON-field lane reached 100% source, critical
and high-severity accuracy, with zero authority change, disclosure or source
bypass. It is selected for this literal-field-reading contract. FTS retrieval
reached about 52.7% overall, 52.4% critical and 23.2% high-severity accuracy and
did not qualify. Both ran locally with zero model and network calls.

The scope is explicit: the 500 pages come from two issuers; temporal cases check
200 scaled/signed facts, 50 contexts and 50 units rather than adjudicate
restatements; workflow cases read constraints rather than execute workflows.
Rendered raster cases test OCR, not every embedded publisher chart. These results
do not establish general investment reasoning, forecast quality, economics or a
no-model verdict. Registered model comparisons remain ineligible under their
existing identity/route and zero-budget records; the separately authorized AAPL
pilot does not change those records.

Registration and reviewed labels:
`results/readiness_continuation/20260930-real-corpus-candidates/`.
Completed local execution and benchmark receipts:
`results/readiness_continuation/20260930-real-corpus-candidates/local-qualification-v1/`.

## Integrated broader local result — October 1, 09:18 UTC

The v6 registration retains the same 500 native pages and 200 injection labels,
then replaces the narrow temporal/workflow readings with 100 complete-period
questions, 100 actual-collection cutoff questions, 100 cross-filing precision
comparisons and 400 configuration fixtures. Each workflow question checks a named
role and the complete configuration. The 700 typed labels were independently
checked against originals or the actual configuration auditor before integration;
all 1,400 answers were checked again against authenticated material. The final
affected source group passed 159 tests, including 51 new regression cases.

All 1,400 cases are conservatively scored at high severity. The deterministic
lane answered every case correctly: 100% source, critical-field and high-severity
accuracy, with zero authority changes, disclosure or source bypass. FTS retrieval
answered 293 cases correctly, 20.9%, and did not qualify; its no-text twin answered
none correctly. All lanes passed the security checks. Local model calls, network
calls and spending were zero. The deterministic lane is selected within this
registered question contract. Neither missing model results nor this selection
establishes a general no-model verdict.

The input originals, actual collection/publication times, page and span locations,
extraction transformations and reader/interpreter source identities remain bound.
V4 and v5 replay remain supported. The actual run exposed excessive SQLite body
copying while ranking; the repair preserves the BM25 order and reads only the
winning retained source. Root's separate review also hardened direct malformed
fact text, namespace, attribute and continuation inputs. Interrupted, changed-engine
and invalid-telemetry attempts remain preserved; none is accepted as a pass.
The final telemetry correction rounds elapsed milliseconds upward to the required
integer without changing the registration, material or executed answers.

Scope remains bounded: two issuers supply the native PDF pages. The cross-filing
pool contained consistent or compatible-precision values, not a demonstrated
unresolved numeric contradiction. Two separately reviewed ServiceNow narrative
cases remain outside these typed operators. General restatement narratives,
publisher chart reasoning, forecasts, economics and model qualification retain
their actual requirements. Configuration fixtures do not prove deployment or
runtime sessions.

Accepted registration, results and execution review:
`results/readiness_continuation/20261001-v6-source-bundle-integration/accepted-local-qualification/`.
Registration: `e550ac25eca071ed043630ec390efa36831aebbdcf795c9d51a20a113dbbccf2`.
Benchmark receipt: `0bbff1099ae23758f5b6ccfff9e63156577fc2fcdad64bc009b8cb5df8302772`.
The earlier literal-field v5 result remains retained under its original scope.

## Subscription registration migration — October 2

`research_qualification_registration/v7` adds explicit Codex subscription source,
full-graph and reviewer lanes. The new immutable registration preserves all
1,400 v6 case/gold bytes and the original zero execution budgets. It does not
rerun or reinterpret the accepted local results. Historical v4/v5/v6 and
OpenRouter registrations retain their original routes and replay.

The runner binds requested model/effort, installed CLI version, input/output/time
limits and execution outcome IDs. Serving-model/revision identity and subscription
allocation cost stay unknown because the CLI does not return them. Unknown cost
cannot win a cost-bounded selection. Sensitive inputs, missing/repeated IDs,
invalid telemetry or runner drift reject qualification. Models run only through
explicit executor selection and the registered gates; deterministic/retrieval
baselines run first. A perfect deterministic baseline leaves no attainable model
accuracy gain for this exact corpus, without establishing a general no-model
verdict. Gold remains outside model input and compared source bytes remain equal.

The affected integrated benchmark/media/client/checkpoint group passed 235 checks
with mocked model/subprocess responses. No real model or corpus rerun occurred.
The supplemental graph receipt under the private
`results/readiness_continuation/20261002-continuation-implementation/codex-full-graph-registration-v2-final/`
binds the final clean source revision. It does not execute a graph.
See [the October 2 evidence checkpoint](../superpowers/checkpoints/2026-10-02-continuation-source-and-data.md)
for registration hashes and remaining economic/operational gates.
