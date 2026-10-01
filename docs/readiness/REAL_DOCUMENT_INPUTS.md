# Reading real documents for qualification

The benchmark now accepts retained web pages, tables, inline financial facts,
PDF pages, PNG/JPEG images, UTF-8 repository documents and saved tool responses.
It does not consult an answer key to extract a document. Existing v4 registrations
still replay through their original JSON-byte-span path.

New media registrations use `research_qualification_registration/v5` and a
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

Every source lane receives the same extracted `research_media_source/v1` bytes.
The paired no-text lane receives no document bytes. Answer labels remain in the
scoring registration and are excluded from adapter inputs. Source descriptors,
original hashes, page numbers and extraction transformations remain in receipts.

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
The required checked 500/300/400/200 corpus and qualification are still separate
work; source tests and inventories cannot satisfy those gates.

The corpus preparation now retains HPE's 180-page and JPMorganChase's 364-page
publisher-original PDFs, with actual download times and custody receipts.
Five hundred distinct native pages have been extracted and bound. The original
187 successful preparations were reused after the font repair; the failed sweep
receipt remains preserved. Prepared pages live under
`results/readiness_continuation/20260930-pdf-page-repaired/`. Questions, labels and
qualification remain pending; this preparation is not a 500-case pass.
