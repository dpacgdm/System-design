# Week 7: Search Systems and Inverted Indexes

---

## 1. Learning Objectives

```
╔════════════════════════════════════════════════════════════════╗
║   AFTER THIS TOPIC, YOU WILL BE ABLE TO:                       ║
╟────────────────────────────────────────────────────────────────╢
║                                                                ║
║   1. Explain how an inverted index works at the data           ║
║      structure level — and why B-tree indexes from SQL         ║
║      cannot solve full-text search at scale                    ║
║                                                                ║
║   2. Walk through the tokenization pipeline: analyzers,        ║
║      tokenizers, filters, stemming, and why mapping            ║
║      choices change search behavior in production              ║
║                                                                ║
║   3. Describe BM25 scoring with enough precision to            ║
║      explain why document length and term frequency            ║
║      matter — and tune relevance in an interview               ║
║                                                                ║
║   4. Diagram Elasticsearch/OpenSearch cluster architecture:    ║
║      nodes, shards, replicas, segments, refresh cycle,         ║
║      and the near-real-time indexing path                      ║
║                                                                ║
║   5. Write production Query DSL: bool queries, filters,        ║
║      aggregations, pagination pitfalls, and when to use        ║
║      search_after vs scroll vs point-in-time                   ║
║                                                                ║
║   6. Diagnose cluster incidents: yellow/red status, split      ║
║      brain, mapping explosions, hot shards, and GC pauses      ║
║      — with exact AWS OpenSearch commands                      ║
║                                                                ║
║   7. Position Elasticsearch as a CQRS read model (Week 5):     ║
║      CDC ingestion, idempotency, rebuild procedures, and       ║
║      the invariant that PostgreSQL remains source of truth     ║
╚════════════════════════════════════════════════════════════════╝
```

---

## 2. Wrong Mental Models (Destroy These First)

```
╔════════════════════════════════════════════════════════════════════╗
║   MENTAL MODEL #1: "Elasticsearch is a database"                   ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Elasticsearch is a distributed inverted-index search      ║
║   engine optimized for relevance-ranked retrieval and              ║
║   aggregations — not ACID transactions, not joins, not             ║
║   source-of-truth writes. Using it as your primary store is        ║
║   how you lose data during split-brain or accidental index         ║
║   deletion.                                                        ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #2: "Just add a LIKE '%keyword%' index"             ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. B-tree indexes (Week 2) support prefix and range          ║
║   lookups on SORTED scalar values. They cannot efficiently         ║
║   answer "find all documents containing 'kubernetes' OR            ║
║   'k8s' ranked by relevance." That's a different data              ║
║   structure problem — inverted indexes exist because B-trees       ║
║   fail here.                                                       ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #3: "Index a document → immediately searchable"     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Near-real-time (NRT) means ~1 second default delay        ║
║   (refresh_interval). Writes go to translog + in-memory buffer;    ║
║   search hits refreshed segments only. Forcing refresh on every    ║
║   write destroys indexing throughput.                              ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #4: "More shards = faster everything"               ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Each shard is a separate Lucene index with overhead.      ║
║   Too many shards → cluster state bloat, heap pressure, slow       ║
║   aggregations, expensive cross-shard coordination. AWS            ║
║   recommends staying under ~25 shards per GB of heap on data       ║
║   nodes — and often far fewer.                                     ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #5: "Replicas are just backups"                     ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Replicas serve read traffic AND provide failover.         ║
║   They double (or triple) storage and indexing work on writes.     ║
║   replica=0 on a single-node dev cluster is fine; replica=0        ║
║   in production is how you get yellow clusters and data loss       ║
║   when a node dies.                                                ║
╠════════════════════════════════════════════════════════════════════╣
║   MENTAL MODEL #6: "Dynamic mapping handles schema for me"         ║
╟────────────────────────────────────────────────────────────────────╢
║   WRONG. Dynamic mapping on high-cardinality fields (user_id,      ║
║   request_id, timestamps as strings) causes mapping explosions —   ║
║   millions of fields, cluster state OOM, index rejections.         ║
║   Explicit mappings with strict dynamic:false are production       ║
║   baseline, not optional hygiene.                                  ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## 3. Core Teaching

### Part A: Why SQL Indexing Cannot Solve Full-Text Search

In Week 2 (SQL Deep Dive), you learned that B-tree indexes excel at:

```
B-TREE STRENGTHS (RECAP FROM WEEK 2):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ✓ Point lookup:     WHERE user_id = 123
  ✓ Range scan:       WHERE created_at > '2024-01-01'
  ✓ Prefix match:     WHERE email LIKE 'alice%'   (uses index)
  ✓ Composite keys:   WHERE user_id = 123 AND status = 'pending'
  ✓ Covering index:   Index-only scan when all columns in index

  ✗ Substring search: WHERE body LIKE '%kubernetes%'
  ✗ Token search:     WHERE body CONTAINS 'docker' AND 'kubernetes'
  ✗ Relevance rank:   ORDER BY relevance_score DESC
  ✗ Fuzzy match:      Find "kubernets" (typo) near "kubernetes"
  ✗ Synonym expand:   "k8s" should match "kubernetes"
```

Why `LIKE '%term%'` fails at scale:

```
TABLE: articles (10 million rows, avg body = 4 KB)

Query: SELECT * FROM articles WHERE body LIKE '%kubernetes%';

EXPLAIN: Seq Scan on articles
  Filter: (body ~~ '%kubernetes%'::text)
  Rows Removed by Filter: 9,999,847
  Actual Rows: 153
  Execution Time: 8423.291 ms

WHAT HAPPENED:
  → B-tree cannot help — leading wildcard defeats index use
  → Database reads EVERY row, scans EVERY byte of body text
  → 10M rows × 4 KB = ~40 GB read from disk
  → Even with SSD: seconds to minutes per query

POSTGRESQL FULL-TEXT SEARCH (tsvector/GIN) IS BETTER BUT LIMITED:

  CREATE INDEX idx_body_fts ON articles USING GIN (to_tsvector('english', body));

  SELECT * FROM articles
  WHERE to_tsvector('english', body) @@ to_tsquery('kubernetes');

  → Uses GIN inverted index — fast for single-table search
  → BUT: no distributed sharding, weak aggregations, no built-in
    horizontal scaling, relevance tuning is crude vs BM25,
    cross-field boosting is painful, no native CDC ecosystem

WHEN PG FTS IS ENOUGH:
  → Single Postgres instance, < 50M documents
  → Simple search, no complex facets/filters
  → Team wants one database, accepts search as secondary feature

WHEN YOU NEED ELASTICSEARCH/OPENSEARCH:
  → Dedicated search SLA (p99 < 100ms at 1000+ QPS)
  → Faceted navigation (brand, price range, category counts)
  → Multi-field relevance tuning (title boost > body)
  → Horizontal scale beyond one Postgres node
  → CQRS read model fed by CDC (Week 5 pattern)
```

The fundamental insight:

```
TWO DIFFERENT INDEX PROBLEMS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  B-TREE (Week 2):          INVERTED INDEX (This topic):
  ─────────────────         ─────────────────────────────
  Index BY row              Index BY term
  "Row 42 → values"         "kubernetes → [doc1, doc7, doc99]"
  Sorted scalar keys        Unsorted token postings
  Exact/range match         Set intersection + scoring
  One row per lookup        Many docs per term

  Phone book by LAST NAME   Book index at back of textbook
  (find person by name)     (find pages mentioning "photosynthesis")
```

---

### Part B: The Inverted Index — Data Structure Deep Dive

An inverted index maps each **term** (token) to a list of **postings** — documents (and positions) where that term appears.

```
DOCUMENTS:
  Doc 1: "Elasticsearch is fast"
  Doc 2: "Search engines use inverted indexes"
  Doc 3: "Elasticsearch uses inverted indexes for fast search"

TOKENIZATION (simplified, lowercase):
  Doc 1: [elasticsearch, is, fast]
  Doc 2: [search, engines, use, inverted, indexes]
  Doc 3: [elasticsearch, uses, inverted, indexes, for, fast, search]

INVERTED INDEX:

  Term              │ Doc IDs (postings list)     │ Term Freq per doc
  ──────────────────┼─────────────────────────────┼──────────────────
  elasticsearch     │ [1, 3]                      │ 1, 1
  fast              │ [1, 3]                      │ 1, 1
  inverted          │ [2, 3]                      │ 1, 1
  indexes           │ [2, 3]                      │ 1, 1
  search            │ [2, 3]                      │ 1, 1
  engines           │ [2]                         │ 1
  use               │ [2]                         │ 1
  uses              │ [3]                         │ 1
  is                │ [1]                         │ 1
  for               │ [3]                         │ 1

QUERY: "elasticsearch search"

  Step 1: Lookup "elasticsearch" → [1, 3]
  Step 2: Lookup "search"        → [2, 3]
  Step 3: Combine (OR):           → [1, 2, 3]
  Step 4: Score each doc (BM25)  → rank [3, 1, 2] perhaps

QUERY: "elasticsearch AND inverted"

  Step 1: [1, 3] ∩ [2, 3] = [3]
  Step 2: Only Doc 3 matches both terms
```

#### Postings Lists and Positions

Production inverted indexes store more than doc IDs:

```
POSTING ENTRY (LUCENE-STYLE):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Term: "kubernetes"
  Document: doc_789
    ├── Term frequency (tf): 4        (appears 4 times in doc)
    ├── Positions: [12, 89, 234, 401] (word offsets — enables phrases)
    ├── Payloads: (optional, e.g., font weight)
    └── Norms: document length factor (for BM25 length normalization)

WHY POSITIONS MATTER:

  Query: "machine learning" (phrase query)
  → Must find "machine" at position N and "learning" at position N+1
  → Without positions: match docs with both words anywhere (sloppy)
  → With positions: exact phrase match or slop=2 (within 2 words)

  Example:
    Doc A: "machine learning is great"     → positions [0, 1] ✓ phrase
    Doc B: "learning about machine parts"  → positions [0, 2] ✗ not adjacent
```

#### Skip Lists and Compression

At billions of postings, lists must be compressed and skippable:

```
LARGE TERM: "the" might appear in 800M documents

  Problem: Intersecting "the" AND "kubernetes" — can't iterate 800M IDs

  Solutions:
  1. STOP WORD REMOVAL — drop "the", "a", "is" at index time
     → Term never enters index (saves space AND query time)

  2. SKIP LISTS — postings encoded in blocks with skip pointers
     → Jump ahead during merge/intersection

  3. FRONT-CODED COMPRESSION — delta-encode sorted doc IDs
     → [100, 105, 112] stored as [100, +5, +7] — highly compressible

  4. ROARING BITMAPS — for dense doc ID sets (analytics use cases)
```

#### Comparison to Week 2 B-Tree

```
╔══════════════════════════════════════════════════════════════╗
║   B-TREE INDEX (Week 2)     │  INVERTED INDEX (Week 7)       ║
╟─────────────────────────────┼────────────────────────────────╢
║   Key: column value         │  Key: token/term               ║
║   Value: row pointer        │  Value: postings list            ║
║   One entry per row         │  One entry per (term, doc) pair  ║
║   O(log n) tree traversal   │  O(1) hash to term → list scan   ║
║   Great for 1:1 lookup      │  Great for 1:many term→docs      ║
║   Maintains sort order      │  Terms usually sorted lexically  ║
║   Range queries natural     │  Range on terms rare (wildcard $)║
╚══════════════════════════════════════════════════════════════╝

  Composite B-tree (user_id, status): like a compound key phone book
  Inverted index: like the index at the back of every textbook you've owned
```

---

### Part C: Tokenization — Analyzers, Tokenizers, and Filters

Before a string enters the inverted index, it passes through an **analyzer** pipeline:

```
RAW TEXT INPUT:
  "The K8s cluster's nodes aren't responding! Email: Bob@Example.COM"

ANALYZER PIPELINE:
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │  CHAR       │ →  │  TOKENIZER  │ →  │  TOKEN      │
  │  FILTERS    │    │             │    │  FILTERS    │
  └─────────────┘    └─────────────┘    └─────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
  Strip HTML,          Split into         Lowercase,
  normalize            tokens on          stop words,
  unicode              whitespace/          stem,
                       punctuation          synonyms

OUTPUT TOKENS (standard analyzer, simplified):
  [k8s, cluster, nodes, aren, respond, email, bob, example, com]

  Note: "aren't" → "aren" (stemmer) or [aren, t] depending on analyzer
  Note: "The" removed (stop word)
  Note: "K8s" preserved as token (synonym mapping would add "kubernetes")
```

#### The Three Components

```
1. CHARACTER FILTERS (pre-tokenization)
   ─────────────────────────────────────
   → html_strip: remove <tags>
   → mapping: "₹" → "INR"
   → pattern_replace: remove punctuation globally

2. TOKENIZER ( splits text into tokens )
   ─────────────────────────────────────
   standard:     Unicode-aware grammar tokenizer (default)
   whitespace:   Split on whitespace only — "foo-bar" stays one token
   keyword:      Entire input = one token (IDs, SKUs, enum values)
   ngram:        "elastic" → [e, el, ela, elas, ...] (autocomplete)
   edge_ngram:   "elastic" → [e, el, ela, elas, elasti, elastic]
   uax_url_email: keeps URLs/emails as single tokens

3. TOKEN FILTERS (post-tokenization)
   ─────────────────────────────────
   lowercase:        "Elasticsearch" → "elasticsearch"
   stop:             remove "the", "is", "at" (language-specific lists)
   stemmer:          "running" → "run", "kubernetes" → "kubernet"
   synonym:          "k8s" ↔ "kubernetes", "tv" ↔ "television"
   word_delimiter:   "PowerShot" → [power, shot, powershot]
   unique:           dedupe tokens in same doc
   shingle:          "new york" → [new, york, new_york] (bigrams)
```

#### Multi-Fields — Same Data, Different Analyses

Production pattern for fields that need multiple search behaviors:

```json
PUT products
{
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "english",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 256
          },
          "autocomplete": {
            "type": "text",
            "analyzer": "autocomplete_analyzer",
            "search_analyzer": "standard"
          }
        }
      },
      "sku": {
        "type": "keyword"
      }
    }
  }
}
```

```
WHY MULTI-FIELDS:

  title          → full-text search ("wireless headphones")
  title.keyword  → exact sort, aggregations, filters ("Bose QC45")
  title.autocomplete → prefix/as-you-type search ("wire" → "wireless...")

  sku as keyword → no tokenization; exact match only

CRITICAL: Index-time analyzer vs search-time analyzer

  Index:  "Running quickly" → [run, quick]     (stemmer at index)
  Search: "run fast"        → [run, fast]      (stemmer at search)
  → Both sides MUST use compatible analysis or terms won't match

  AUTocomplete SPECIAL CASE:
  Index:  edge_ngram → [e, el, ela, elas, elastic, elasticsearch]
  Search: standard   → [elastic]  (don't search with ngrams!)
  → search_analyzer differs from analyzer — intentional
```

#### Custom Analyzer Example (AWS OpenSearch)

```json
PUT products
{
  "settings": {
    "analysis": {
      "filter": {
        "english_stemmer": {
          "type": "stemmer",
          "language": "english"
        },
        "product_synonyms": {
          "type": "synonym",
          "synonyms": [
            "k8s, kubernetes",
            "tv, television",
            "phone, mobile, cellphone"
          ]
        }
      },
      "analyzer": {
        "product_analyzer": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": [
            "lowercase",
            "product_synonyms",
            "english_stemmer"
          ]
        }
      }
    }
  }
}
```

```
PRODUCTION RULES FOR ANALYZERS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. NEVER change analyzer on a live field without reindex
     → Same text produces different tokens → silent search breakage

  2. Synonym expansion at INDEX time vs SEARCH time:
     Index-time:  "k8s" doc matches "kubernetes" query AND vice versa
                  BUT: synonyms baked in — changing synonym file = reindex
     Search-time: flexible synonym updates, but slower queries
     Production:  search-time synonyms for frequently updated lists;
                  index-time for stable domain vocabulary

  3. Stop words: default English stop list removes "is", "the"
     → Query "to be or not to be" returns nothing useful
     → For log search, use whitespace analyzer or custom minimal stop list

  4. Language detection: multi-language catalogs need per-field or
     per-document language-specific analyzers (Elasticsearch: _lang field)
```

---

### Part D: BM25 — How Relevance Scoring Works

Elasticsearch/OpenSearch default similarity since Lucene 6: **BM25** (Best Matching 25). It replaced TF-IDF because BM25 handles document length and term frequency saturation better.

#### TF-IDF Recap (What BM25 Replaces)

```
TF-IDF INTUITION (LEGACY — KNOW FOR INTERVIEWS):

  score(doc, query) = Σ  tf(t,d) × idf(t)
                       t∈query

  tf(t,d)  = term frequency in document (how often "kubernetes" in doc)
  idf(t)   = inverse document frequency = log(N / df(t))
             N = total docs, df(t) = docs containing term t

  IDF effect: rare terms ("kubernetes") score higher than common ("the")

  TF PROBLEM: Linear TF growth rewards keyword stuffing
    Doc with "kubernetes" 100 times beats doc with 5 meaningful mentions

  LENGTH PROBLEM: Long docs accumulate higher TF by chance
    10,000-word doc mentions "docker" 20 times vs 200-word doc mentions 3
```

#### BM25 Formula

```
BM25 SCORE FOR TERM t IN DOCUMENT d:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                    df(t) × (k1 + 1)
  IDF(t) = log( ─────────────────────── + 1 )
                    N - df(t) + 0.5

                    tf(t,d) × (k1 + 1)
  TF(t,d) = ─────────────────────────────────────────
             tf(t,d) + k1 × (1 - b + b × |d|/avgdl)

  score(d,q) = Σ  IDF(t) × TF(t,d)
               t∈q∩d

WHERE:
  tf(t,d)  = term frequency of t in document d
  |d|      = document length (field length in tokens)
  avgdl    = average document length in the collection
  df(t)    = document frequency (docs containing t)
  N        = total number of documents
  k1       = term frequency saturation parameter (default 1.2)
  b        = length normalization parameter (default 0.75)

INTUITION:

  k1 controls TF saturation:
    k1 = 0  → binary TF (term present or not)
    k1 = 1.2 (default) → diminishing returns after ~3-5 occurrences
    k1 = 2.0 → more weight on repeated terms

  b controls length penalty:
    b = 0   → ignore document length
    b = 0.75 (default) → moderate penalty for long docs
    b = 1.0 → full length normalization

  IDF with +0.5 smoothing prevents negative IDF for very common terms
```

#### Worked Example

```
COLLECTION: 1,000,000 documents, avgdl = 500 tokens

Document A: 200 tokens, "kubernetes" appears 3 times
Document B: 2000 tokens, "kubernetes" appears 10 times
Query: "kubernetes"
df("kubernetes") = 50,000

IDF = log(1 + (1,000,000 - 50,000 + 0.5) / (50,000 + 0.5))
    ≈ log(1 + 19) ≈ 3.0

Document A TF component (k1=1.2, b=0.75):
  |d|=200, avgdl=500 → length norm = 1 - 0.75 + 0.75×(200/500) = 0.55
  TF_A = 3 × 2.2 / (3 + 1.2 × 0.55) = 6.6 / 3.66 ≈ 1.80
  Score_A ≈ 3.0 × 1.80 ≈ 5.4

Document B TF component:
  |d|=2000 → length norm = 1 - 0.75 + 0.75×(2000/500) = 3.25
  TF_B = 10 × 2.2 / (10 + 1.2 × 3.25) = 22 / 13.9 ≈ 1.58
  Score_B ≈ 3.0 × 1.58 ≈ 4.7

RESULT: Shorter, focused doc A wins despite lower raw TF count.
  → BM25 penalizes keyword stuffing AND document length
```

#### Boosting and Function Scores

```json
GET products/_search
{
  "query": {
    "bool": {
      "must": {
        "multi_match": {
          "query": "wireless headphones",
          "fields": ["title^3", "description", "brand^2"]
        }
      },
      "filter": [
        { "term": { "in_stock": true } }
      ]
    }
  },
  "rescore": {
    "window_size": 100,
    "query": {
      "rescore_query": {
        "function_score": {
          "functions": [
            {
              "field_value_factor": {
                "field": "popularity_score",
                "factor": 1.2,
                "modifier": "log1p"
              }
            },
            {
              "gauss": {
                "release_date": {
                  "origin": "now",
                  "scale": "30d",
                  "decay": 0.5
                }
              }
            }
          ],
          "score_mode": "sum",
          "boost_mode": "multiply"
        }
      }
    }
  }
}
```

```
BOOSTING RULES:
━━━━━━━━━━━━━━

  title^3       → title term match counts 3× toward BM25 score
  filter clause → NO score contribution (cacheable, fast)
  must clause   → required, contributes to score
  should clause → optional, boosts score if matched
  function_score → business signals (popularity, recency, distance)

  FILTERS vs QUERIES:
    filter: { "term": { "category": "electronics" } }  → yes/no, cached
    must:   { "match": { "title": "headphones" } }     → scored

  Production: put high-selectivity predicates in filter context
    → Bitset cached across requests
    → Doesn't affect relevance ranking
```

---

### Part E: Lucene Segments — The Physical Storage Layer

Elasticsearch/OpenSearch is a distributed wrapper around **Apache Lucene**. Each shard is a Lucene index composed of immutable **segments**.

```
WRITE PATH (SIMPLIFIED):
━━━━━━━━━━━━━━━━━━━━━━━

  1. Document arrives at primary shard
  2. Parsed using mapping + analyzer → tokens
  3. Tokens added to IN-MEMORY BUFFER (indexing buffer, heap)
  4. Also written to TRANSLOG (transaction log, disk — durability)
  5. Buffer fills OR refresh triggered → new SEGMENT written to disk
  6. Segment is IMMUTABLE — never modified after creation
  7. Background MERGE combines small segments into larger ones

SEGMENT STRUCTURE ON DISK:
  ┌─────────────────────────────────────────────┐
  │  Segment N (immutable)                       │
  │  ├── _0.fnm  (field names)                   │
  │  ├── _0.tim  (terms dictionary)              │
  │  ├── _0.tip  (terms index — FST for lookup)  │
  │  ├── _0.doc  (postings: doc ids + freqs)     │
  │  ├── _0.pos  (positions)                     │
  │  ├── _0.pay  (payloads)                        │
  │  ├── _0.nvd  (norms — doc length for BM25)     │
  │  ├── _0.dvd  (doc values — columns for aggs)   │
  │  └── _0 liv  (live docs — tombstones for deletes)│
  └─────────────────────────────────────────────┘

DELETE/UPDATE REALITY:
  Lucene segments are append-only.
  DELETE = tombstone in live docs bitset (marked deleted, not removed)
  UPDATE = delete old doc + insert new doc (two operations!)
  → High update rate = segment bloat + merge pressure
  → Immutable model is WHY reindexing is expensive
```

#### Segment Merge Policy

```
MANY SMALL SEGMENTS (after heavy indexing):
  [1K docs][2K docs][1K docs][500 docs][3K docs]...

MERGE BACKGROUND PROCESS:
  Picks segments of similar size, merges into one
  [1K+2K → 3K merged][1K+500+3K → 4.5K merged]...

WHY MERGES MATTER:
  Search must query ALL segments → more segments = slower search
  Each segment has overhead (term dictionary loaded)
  Merges are I/O and CPU intensive → cause indexing/search latency spikes

  index.merge.policy settings tune aggressiveness
  forcemerge API: merge to 1 segment — use ONLY for read-only indices
    → forcemerge on live index = production incident (blocks, heap spike)
```

---

### Part F: Elasticsearch/OpenSearch Cluster Architecture

```
CLUSTER TOPOLOGY:
━━━━━━━━━━━━━━━━

                    ┌─────────────────────────────┐
                    │      Cluster: prod-search    │
                    │      (unique cluster name)   │
                    └─────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
  ┌───────────┐              ┌───────────┐              ┌───────────┐
  │ Master-   │              │ Data Node │              │ Coordinating│
  │ eligible  │              │ (hot)     │              │ Node (×3)   │
  │ (3 nodes) │              │ r6g.xlarge│              │ c6g.large   │
  └───────────┘              └───────────┘              └───────────┘
        │                           │                           │
        │ Cluster state             │ Stores shards               │ Routes requests
        │ Index metadata            │ Executes queries            │ Aggregations merge
        │ Shard allocation          │ Indexing                    │ No data storage
        │                           │                           │
        └───────────────────────────┴───────────────────────────┘

NODE ROLES (OpenSearch 2.x / ES 7.10+):
  cluster_manager  — elected leader, cluster state (formerly "master")
  data           — stores shards, CRUD, search
  ingest         — preprocessing pipelines (enrich, geoip)
  coordinating   — client-facing, scatter-gather (often default on all)
  ml             — machine learning jobs (OpenSearch)
  remote_cluster_client — cross-cluster search
```

#### Index → Shard → Replica Hierarchy

```
INDEX: products-2024
  │
  ├── Primary Shard 0  (node-A)  ──replicate──►  Replica 0 (node-B)
  ├── Primary Shard 1  (node-B)  ──replicate──►  Replica 1 (node-C)
  ├── Primary Shard 2  (node-C)  ──replicate──►  Replica 2 (node-A)
  └── Primary Shard 3  (node-A)  ──replicate──►  Replica 3 (node-B)

  number_of_shards: 4      (fixed at index creation — hard to change)
  number_of_replicas: 1    (adjustable live — 1 replica = 2 total copies)

ROUTING:
  document_id → hash(routing_key) mod num_primary_shards → shard_id
  Default routing_key = _id
  Custom routing: same customer_id always → same shard (locality)
    POST /orders/_doc/123?routing=customer_456

  DANGER: routing hotspots — all docs with same routing → one hot shard
```

#### Request Flow: Search Query

```
CLIENT: GET /products/_search?q=headphones
                │
                ▼
        COORDINATING NODE
                │
    ┌───────────┼───────────┬───────────┐
    ▼           ▼           ▼           ▼
 Shard 0     Shard 1     Shard 2     Shard 3
 (query)     (query)     (query)     (query)
 (local      (local      (local      (local
  BM25)       BM25)       BM25)       BM25)
    │           │           │           │
    └───────────┴───────────┴───────────┘
                │
                ▼
        COORDINATING NODE
        Merge top-K from each shard
        (global ranking — approximate)
                │
                ▼
           Response to client

  QUERY PHASE:  scatter to all shards, collect doc IDs + scores
  FETCH PHASE:  retrieve full _source for top hits (if needed)

  SHARD-LEVEL SCORING IS LOCAL:
    IDF computed per shard (unless dfs_query_then_fetch)
    → Rare term stats skewed on small shards
    → Production: prefer balanced shard sizes (~10-50 GB)
```

#### Request Flow: Index Document

```
CLIENT: POST /products/_doc { "title": "...", "price": 99 }
                │
                ▼
        COORDINATING NODE
        hash(_id) mod 4 → Shard 2 primary
                │
                ▼
        PRIMARY SHARD 2 (node-C)
        1. Validate mapping
        2. Run ingest pipeline (if any)
        3. Analyze fields → tokens
        4. Write to memory buffer + translog
        5. Replicate to replica shard 2 (node-A)
        6. Acknowledge after in-sync replica (quorum)
                │
                ▼
        Response: 201 Created

  consistency: wait_for_active_shards (default 1)
  index.refresh_interval: 1s → new segment visible to search
  index.translog.durability: async | request (sync on every doc)
```

---

### Part G: Sharding and Replication — Design and Operations

```
SHARD COUNT DECISION (PRODUCTION HEURICSTIC):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Target shard size: 10 GB – 50 GB (search-heavy: smaller; log-heavy: larger)

  Formula:
    primary_shards = ceil(expected_data_volume_GB / target_shard_size_GB)

  Example:
    500 GB product catalog, 30 GB target → 17 primary shards → round to 20
    With 1 replica: 40 shard copies across cluster

  AWS OpenSearch sizing (r6g.2xlarge, 64 GB RAM):
    Heap ≈ 32 GB (50% of RAM — NEVER exceed 50% heap on data nodes)
    Max shards per node guideline: ~25 shards per GB heap → ~800 shards max
    But practical limit lower due to merge/search overhead

WHEN TO REINDEX FOR SHARD COUNT:
  Created index with 5 shards, now 2 TB data → 400 GB/shard (too big)
  → Create new index with 40 shards
  → Reindex API: POST _reindex { source: {index: old}, dest: {index: new} }
  → Alias swap: zero-downtime cutover
  → Delete old index after validation

REPLICA COUNT TRADEOFFS:
  replicas = 0  → no redundancy, no read scaling, yellow if node lost
  replicas = 1  → tolerate 1 node failure, 2× storage, read QPS ~2×
  replicas = 2  → tolerate 2 node failures, 3× storage

  Write path: primary + all replicas must index (slower with more replicas)
  Read path:  load balanced across primary + replicas
```

#### Routing and Co-Location

```json
PUT orders_2024
{
  "settings": {
    "number_of_shards": 12,
    "number_of_replicas": 1,
    "routing_partition_size": 1
  },
  "mappings": {
    "properties": {
      "customer_id": { "type": "keyword" },
      "order_total": { "type": "float" }
    }
  }
}

POST orders_2024/_doc/ord_789?routing=customer_456
{
  "customer_id": "customer_456",
  "order_total": 149.99
}

GET orders_2024/_search?routing=customer_456
{
  "query": { "term": { "customer_id": "customer_456" } }
}
```

```
ROUTING BENEFITS:
  All of customer_456's orders on ONE shard
  → Search with routing hits 1 shard instead of 12
  → 12× less coordination overhead for customer-scoped queries

ROUTING RISKS:
  Mega-customer with 50% of orders → shard hotspot
  → Monitor per-shard doc count and indexing rate
  → May need custom routing hash + overflow index
```

---

### Part H: Near-Real-Time (NRT) Indexing

Search engines trade **immediate consistency** for **indexing throughput**. This is the NRT model.

```
TIMELINE OF A WRITE:
━━━━━━━━━━━━━━━━━━

  T+0ms:    Document indexed to primary shard
            → In memory indexing buffer
            → Translog fsync (if async, may delay)

  T+0ms:    Replicated to replica(s)
            → Client receives 201 Created
            → Document durable in translog
            → NOT YET SEARCHABLE

  T+1000ms: Refresh triggered (default refresh_interval: 1s)
            → Buffer flushed to new on-disk segment
            → Segment opened for search (reference refreshed)
            → Document NOW searchable

  T+5min:   Background merge compacts segments

  T+30min:  Translog truncated after flush (safe — data in segments)

REFRESH INTERVAL TUNING:
  index.refresh_interval: "1s"   (default — good for most search)
  index.refresh_interval: "30s"  (bulk indexing — higher throughput)
  index.refresh_interval: "-1"   (disable auto-refresh during bulk load)

  POST /products/_refresh   → manual refresh (avoid in steady state)
  POST /products/_settings  { "refresh_interval": "1s" }  → restore after bulk

CONSISTENCY GUARANTEES:
  After 201 response: document recoverable from translog (get-by-id works
    on primary even before refresh in some cases via real-time get)
  After refresh: document appears in search results
  After flush: translog trimmed, fully in segments

  NOT ACID across documents:
    Bulk index 1000 docs → some may be searchable before others
    No cross-document transaction
```

#### Bulk Indexing Pattern

```json
POST _bulk
{ "index": { "_index": "products", "_id": "1" } }
{ "title": "Widget A", "price": 19.99 }
{ "index": { "_index": "products", "_id": "2" } }
{ "title": "Widget B", "price": 29.99 }

BULK SETTINGS FOR REINDEX (temporary):
  refresh_interval: -1
  number_of_replicas: 0        (restore after bulk complete!)
  translog.durability: async
  translog.sync_interval: 30s

  Batch size: 5-15 MB per bulk request (not doc count — byte size)
  Workers: 1 bulk worker per shard (more = contention)

AFTER BULK:
  POST /products/_refresh
  PUT /products/_settings { "number_of_replicas": 1, "refresh_interval": "1s" }
```

---

### Part I: Query DSL — Production Patterns

The Query DSL is JSON-based. Master the **bool** query first — everything else composes from it.

```json
GET products/_search
{
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "noise cancelling headphones",
            "fields": ["title^3", "description"],
            "type": "best_fields",
            "operator": "and"
          }
        }
      ],
      "filter": [
        { "term": { "in_stock": true } },
        { "range": { "price": { "gte": 50, "lte": 300 } } },
        { "terms": { "brand": ["Sony", "Bose", "Sennheiser"] } }
      ],
      "should": [
        { "term": { "prime_eligible": { "value": true, "boost": 2 } } }
      ],
      "must_not": [
        { "term": { "discontinued": true } }
      ],
      "minimum_should_match": 0
    }
  },
  "sort": [
    { "_score": "desc" },
    { "popularity": "desc" }
  ],
  "from": 0,
  "size": 20,
  "_source": ["title", "price", "brand", "image_url"],
  "track_total_hits": true
}
```

#### Query Types Reference

```
FULL-TEXT (analyzed — BM25 scored):
  match           → standard full-text on one field
  multi_match     → same query across multiple fields
  match_phrase    → tokens must be adjacent (slop for gap)
  query_string    → Lucene syntax (powerful, footgun — disable in prod APIs)

EXACT (not analyzed — filter context preferred):
  term            → exact match on keyword field
  terms           → exact match any of list
  range           → numeric/date ranges
  exists          → field present
  prefix          → keyword prefix (can be slow)
  wildcard        → * and ? patterns (expensive — avoid leading wildcard)

COMPOUND:
  bool            → must/should/must_not/filter
  dis_max         → best score from multiple queries (disjunction max)
  constant_score  → fixed score (wrap filter for scored context)

NESTED / JOIN-LIKE:
  nested          → query nested object arrays independently
  has_child       → parent-child join (legacy pattern)
  nested is preferred for object arrays within same doc

GEO:
  geo_distance    → within radius
  geo_bounding_box
  geo_shape
```

#### Pagination — The Deep Pagination Problem

```
from + size PAGINATION:
  GET /products/_search { "from": 9900, "size": 100 }
  → Coordinating node must collect and sort top 10,000 from EACH shard
  → Memory: from + size limited to index.max_result_window (default 10,000)
  → Page 100 at size 100 = OK; page 500 at size 100 = REJECTED

SCROLL (deprecated for user-facing — OK for batch export):
  Initial: { "size": 1000, "sort": ["_doc"] } + scroll=5m
  → Maintains search context (heap cost)
  → Open scroll contexts = cluster memory leak if not cleared

SEARCH_AFTER (production pagination for deep pages):
  {
    "size": 20,
    "sort": [{ "created_at": "desc" }, { "_id": "asc" }],
    "search_after": [1699900000000, "doc_abc123"]
  }
  → Stateless cursor from last hit's sort values
  → Requires unique tiebreaker (_id)
  → Cannot jump to arbitrary page number — next/prev only

POINT IN TIME (PIT) + search_after (OpenSearch 1.x / ES 7.10+):
  POST /products/_pit?keep_alive=5m  → pit_id
  GET /_search { "pit": { "id": "...", "keep_alive": "5m" }, ... }
  → Consistent view even while indexing continues
  → Preferred for export and infinite scroll UIs
```

---

### Part J: Aggregations — Analytics Without Hits

Aggregations compute metrics/buckets over the inverted index using **doc values** (columnar field cache).

```json
GET products/_search
{
  "size": 0,
  "query": {
    "match": { "title": "headphones" }
  },
  "aggs": {
    "by_brand": {
      "terms": {
        "field": "brand.keyword",
        "size": 20,
        "order": { "_count": "desc" }
      },
      "aggs": {
        "avg_price": { "avg": { "field": "price" } },
        "price_ranges": {
          "range": {
            "field": "price",
            "ranges": [
              { "to": 50 },
              { "to": 100, "from": 50 },
              { "to": 200, "from": 100 },
              { "from": 200 }
            ]
          }
        }
      }
    },
    "price_histogram": {
      "histogram": {
        "field": "price",
        "interval": 25
      }
    },
    "monthly_releases": {
      "date_histogram": {
        "field": "release_date",
        "calendar_interval": "month"
      }
    }
  }
}
```

```
AGGREGATION TYPES:
━━━━━━━━━━━━━━━━━━

  BUCKET (group by):
    terms          → top N values (brand, category)
    date_histogram → time buckets
    range          → numeric ranges
    filter         → split by query
    nested         → agg within nested objects

  METRIC (compute):
    avg, sum, min, max, stats, extended_stats
    cardinality    → approximate distinct count (HyperLogLog++)
    percentiles    → p50, p95, p99

  PIPELINE (agg of aggs):
    derivative, moving_avg, cumulative_sum

PERFORMANCE RULES:
  "size": 0  → hits not fetched, agg only (much faster)
  keyword fields for terms aggs (not analyzed text)
  cardinality is approximate — ±2% error typical, tunable precision_threshold
  deep nesting (brand → category → subcategory → price stats) = heap heavy
  use "execution_hint": "map" vs "global_ordinals" for high-cardinality terms
```

#### Nested Aggregations

```json
PUT products
{
  "mappings": {
    "properties": {
      "title": { "type": "text" },
      "reviews": {
        "type": "nested",
        "properties": {
          "rating": { "type": "integer" },
          "author": { "type": "keyword" }
        }
      }
    }
  }
}

GET products/_search
{
  "size": 0,
  "aggs": {
    "reviews": {
      "nested": { "path": "reviews" },
      "aggs": {
        "avg_rating": { "avg": { "field": "reviews.rating" } },
        "rating_distribution": {
          "terms": { "field": "reviews.rating" }
        }
      }
    }
  }
}
```

```
WITHOUT nested type:
  reviews array flattened → rating from review A paired with author from review B
  → Wrong counts, wrong averages — silent data corruption in dashboards

WITH nested:
  Each review object treated as independent hidden document
  → Correct per-review aggs, ~10-20% indexing overhead
```

---

### Part K: Mappings and Schema Design

```json
PUT products-v2
{
  "settings": {
    "number_of_shards": 6,
    "number_of_replicas": 1,
    "analysis": {
      "analyzer": {
        "product_analyzer": {
          "tokenizer": "standard",
          "filter": ["lowercase", "english_stemmer"]
        }
      }
    }
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "sku":           { "type": "keyword" },
      "title":         { "type": "text", "analyzer": "product_analyzer",
                           "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } } },
      "description":   { "type": "text", "analyzer": "product_analyzer" },
      "brand":         { "type": "keyword" },
      "category_path": { "type": "keyword" },
      "price":         { "type": "scaled_float", "scaling_factor": 100 },
      "in_stock":      { "type": "boolean" },
      "created_at":    { "type": "date" },
      "location":      { "type": "geo_point" },
      "attributes": {
        "type": "nested",
        "properties": {
          "name":  { "type": "keyword" },
          "value": { "type": "keyword" }
        }
      }
    }
  }
}
```

```
FIELD TYPE CHEAT SHEET:
━━━━━━━━━━━━━━━━━━━━━━━

  text         → full-text search (analyzed)
  keyword      → exact match, sort, aggregations
  long/integer → numeric range, sort
  scaled_float → money (integer storage, float semantics)
  date         → range, date_histogram
  boolean      → filter
  geo_point    → geo_distance queries
  nested       → array of objects (independent aggs)
  flattened    → dynamic key-value without mapping explosion (limited aggs)

  dynamic: strict  → reject unknown fields (PRODUCTION DEFAULT)
  dynamic: false   → ignore unknown fields (silent drop — dangerous)
  dynamic: true    → auto-map (dev only)
```

---

### Part L: CQRS Read Model Integration (Week 5 Tie-In)

From Week 5 (Database Scaling Patterns, Rung 6), Elasticsearch is the canonical **read model** for full-text search — not the source of truth.

```
CQRS ARCHITECTURE WITH ELASTICSEARCH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

   App WRITE path
       │
       ▼
   ┌──────────────┐
   │ PostgreSQL   │  ← SOURCE OF TRUTH (ACID, normalized)
   │  (primary)   │
   └──┬───────────┘
      │  WAL → Debezium (CDC) → Kafka topic: db.products
      │
      ├──► Elasticsearch indexer consumer
      │         │
      │         ▼
      │    ┌─────────────────┐
      │    │ ES Index:       │  ← READ MODEL (denormalized, searchable)
      │    │ products-v3     │
      │    └─────────────────┘
      │
      └──► Redis / ClickHouse / other read models...

   App READ path:
     search?q=headphones     → Elasticsearch ONLY
     getProduct(id)          → Redis cache → PG fallback
     checkout / write        → PostgreSQL ONLY

INVARIANTS (FROM WEEK 5 — NON-NEGOTIABLE):
  1. PG wins every conflict. ES is eventually consistent.
  2. Every ES document must be rebuildable from PG + CDC replay.
  3. Consumer idempotency: CDC delivers duplicates — dedupe by event_id/LSN.
  4. DELETE in PG → DELETE in ES (tombstone handling — Week 5 CDC failures).
  5. Named owner for index schema, lag alerts, and rebuild runbook.
```

#### Indexer Consumer Pattern

```python
# Pseudocode — production ES indexer from Kafka CDC events

def handle_event(event):
    op = event["op"]  # c=create, u=update, d=delete, r=snapshot read
    doc_id = str(event["after"]["id"] if op != "d" else event["before"]["id"])

    if op == "d":
        es.delete(index=INDEX_NAME, id=doc_id, ignore=[404])
        return

    doc = denormalize(event["after"])  # join brand name, category path, etc.
    es.index(
        index=INDEX_NAME,
        id=doc_id,
        document=doc,
        op_type="index"  # upsert semantics
    )

def denormalize(row):
    # Denormalize ON WRITE to read model — never join at query time in ES
    return {
        "sku": row["sku"],
        "title": row["title"],
        "brand": row["brand_name"],      # joined at index time from brands table
        "category_path": row["category"], # materialized path: "Electronics/Audio"
        "price": row["price_cents"] / 100,
        "in_stock": row["inventory_count"] > 0,
        "updated_at": row["updated_at"]
    }
```

```
RECONCILIATION (DETECT DRIFT):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Nightly job:
    SELECT id FROM products WHERE updated_at > :last_check
    Compare count + checksum sample against ES

  Metrics:
    es_indexer_lag_seconds (Kafka consumer lag)
    es_doc_count vs pg_row_count (per entity type)
    es_index_error_rate

  REBUILD PROCEDURE (document before you need it):
    1. Create products-v4 index with new mapping
    2. Snapshot PG → bulk index (or replay Kafka from beginning)
    3. Dual-write or catch-up from CDC offset
    4. Validate: random 10K doc hash compare
    5. Alias swap: products → products-v4
    6. Delete products-v3 after 7-day rollback window

  WHEN TO REBUILD vs REINDEX:
    Mapping change (analyzer, field type) → new index + reindex
    Logical corruption → rebuild from PG
    Shard count change → reindex API to new index
```

#### Alias Strategy for Zero-Downtime

```json
POST _aliases
{
  "actions": [
    { "add": { "index": "products-v4", "alias": "products" } },
    { "remove": { "index": "products-v3", "alias": "products" } }
  ]
}

  Application ALWAYS queries alias "products" — never concrete index name
  Blue/green index migrations without app deploy
```

---

## 4. Concrete Examples

### Example 1: E-Commerce Product Search (AWS OpenSearch)

```
SYSTEM: Mid-size e-commerce, 8M SKUs, 2000 search QPS peak, p99 < 150ms

AWS OPENSEARCH DOMAIN:
  Engine: OpenSearch 2.11
  Instance: 6 × r6g.2xlarge.search (data)
            3 × c6g.xlarge.search (dedicated masters — cluster_manager role)
  Storage: 500 GB gp3 EBS per data node (3000 IOPS, 125 MB/s)
  Multi-AZ: 3 AZ, zone awareness enabled
  Encryption: at-rest (KMS), node-to-node TLS
  Fine-grained access: IAM + internal user database, role mapping

INDEX DESIGN:
  products (alias) → products-v7 (concrete)
  12 primary shards × 1 replica = 24 shard copies
  ~40 GB per shard at steady state

INGESTION:
  Debezium CDC from Aurora PostgreSQL → MSK (Kafka) → 4 indexer pods
  Bulk size: 8 MB, refresh_interval: 1s during steady state
  Lag SLA: p99 < 30 seconds from PG commit to ES searchable

QUERY PATTERN:
  User search bar → multi_match on title^3, brand^2, description
  Facets: brand (terms), price (range), category (terms)
  Filters: in_stock=true, marketplace_id (tenant isolation)
  Sort: _score desc, then popularity desc
  Personalization: function_score on user's preferred brands (should clause)

COST (approximate us-east-1):
  Data nodes: 6 × r6g.2xlarge ≈ $1.90/hr × 6 × 730 ≈ $8,322/mo
  Master nodes: 3 × c6g.xlarge ≈ $0.34/hr × 3 × 730 ≈ $745/mo
  EBS: 6 × 500 GB gp3 ≈ $480/mo
  Total domain: ~$9,500/mo (excluding MSK, data transfer)
```

### Example 2: Application Log Search (Observability)

```
SYSTEM: 50 TB/day logs, 14-day retention, 500 analyst queries/day

INDEX STRATEGY: Time-based indices (NOT one giant index)
  logs-2024.07.06  (daily rollover)
  logs-2024.07.05
  ...

INDEX TEMPLATE:
  30 primary shards (write-heavy, no relevance scoring needed)
  replicas: 1
  refresh_interval: 30s (not user-facing search latency)
  codec: best_compression

MAPPING:
  @timestamp: date
  level: keyword
  service: keyword
  trace_id: keyword
  message: text, analyzer: standard (minimal — preserve log tokens)
  kubernetes.pod.name: keyword

  dynamic: strict — reject arbitrary JSON fields from log agents

INGESTION:
  Fluent Bit → OpenSearch Ingestion pipeline (managed) OR Logstash
  OR direct bulk from application (avoid per-log REST calls)

QUERY PATTERN:
  filter: service="payment-api" AND level="ERROR"
          AND @timestamp:[now-1h TO now]
  NO scoring — sort by @timestamp desc
  Aggregations: error count by service (terms), timeline (date_histogram)

ILM (Index Lifecycle Management):
  Hot (0-2 days):   full replicas, fast storage
  Warm (3-7 days):  reduce replicas to 0, forcemerge to 1 segment
  Cold (8-14 days): searchable snapshots (S3-backed, cheaper)
  Delete (14+ days): delete index
```

### Example 3: SaaS Multi-Tenant Search

```
PROBLEM: 10,000 tenants, each searches only their data

ANTI-PATTERN: Separate index per tenant
  → 10,000 indices × shards = cluster state explosion
  → Master node OOM, allocation failures

PATTERN A — Single index + tenant filter (most SaaS):
  Every document has tenant_id (keyword)
  Every query MUST include filter: { "term": { "tenant_id": "t_abc" } }
  Security: document-level security (OpenSearch FGAC) or app-enforced filter
  Routing optional: routing=tenant_id for large tenants

PATTERN B — Index per tenant tier:
  tenants_free → shared index with tenant_id filter
  tenants_enterprise → dedicated index per customer (100 customers)
  Hybrid: small tenants share, whale tenants isolated

SECURITY (AWS OpenSearch FGAC):
  Role: tenant_t_abc_reader
  Index permission: products, query: {"term": {"tenant_id": "t_abc"}}
  DLS (document level security): enforce tenant_id match server-side
  → Defense in depth — app filter + ES DLS
```

### Example 4: Autocomplete / Typeahead

```
USER TYPES: "wire"

INDEX-TIME (edge_ngram):
  "wireless headphones" → tokens: w, wi, wir, wire, wirel, wirele, ...

SEARCH-TIME (standard analyzer):
  Query "wire" → token [wire] — matches prefix ngrams

MAPPING:
  "title": {
    "type": "text",
    "analyzer": "autocomplete_index",
    "search_analyzer": "autocomplete_search",
    "fields": {
      "completion": {
        "type": "completion",
        "contexts": [
          { "name": "category", "type": "category" }
        ]
      }
    }
  }

ALTERNATIVE: completion suggester (FST-based, faster for pure prefix)
  POST products/_search { "suggest": { "product-suggest": {
    "prefix": "wire",
    "completion": { "field": "title.completion", "size": 10,
      "contexts": { "category": ["electronics"] }
    }
  }}}

TRADEOFF:
  edge_ngram: flexible, works with bool queries, larger index
  completion: blazing fast suggest, separate field, less flexible ranking
```

### Example 5: Geo + Text Search (Marketplace)

```json
GET listings/_search
{
  "query": {
    "bool": {
      "must": {
        "multi_match": {
          "query": "vintage guitar",
          "fields": ["title^2", "description"]
        }
      },
      "filter": {
        "geo_distance": {
          "distance": "25mi",
          "location": { "lat": 37.7749, "lon": -122.4194 }
        }
      }
    }
  },
  "sort": [
    {
      "_geo_distance": {
        "location": { "lat": 37.7749, "lon": -122.4194 },
        "order": "asc",
        "unit": "mi"
      }
    }
  ]
}
```

```
GEO NOTES:
  location field type: geo_point (lat/lon object or "lat,lon" string)
  geo_distance filter uses BKD-tree index — fast
  Sorting by distance requires doc values on geo_point
  For heavy geo: consider dedicated geo index or PostGIS for complex polygons
```

---

## 5. Production Patterns

```
PATTERN 1: ALIAS-BASED INDEX VERSIONING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Never query concrete index names in application code.
  Always use aliases: products, logs, orders

  Migration flow:
    Create products-v8 → bulk reindex → validate → atomic alias swap
  Rollback: swap alias back to products-v7 (keep old index 7 days)


PATTERN 2: INDEX TEMPLATES + COMPOSABLE INDEX TEMPLATE (v2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PUT _index_template/products_template
  {
    "index_patterns": ["products-v*"],
    "priority": 200,
    "template": {
      "settings": { "number_of_shards": 12, "number_of_replicas": 1 },
      "mappings": { ... }
    }
  }

  New index products-v9 auto-gets correct settings/mappings


PATTERN 3: INGEST PIPELINES (ENRICH AT INDEX TIME)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PUT _ingest/pipeline/enrich-product
  {
    "processors": [
      { "set": { "field": "indexed_at", "value": "{{_ingest.timestamp}}" } },
      { "lowercase": { "field": "brand" } },
      { "remove": { "field": "internal_cost", "ignore_missing": true } },
      {
        "geoip": {
          "field": "client_ip",
          "target_field": "geo",
          "ignore_missing": true
        }
      }
    ]
  }

  Index with: POST /products/_doc?pipeline=enrich-product

  Use for: PII stripping, normalization, GeoIP — NOT for cross-service joins


PATTERN 4: SEARCH TEMPLATE (PARAMETERIZED QUERIES)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PUT _scripts/product_search
  {
    "script": {
      "lang": "mustache",
      "source": {
        "query": {
          "bool": {
            "must": { "multi_match": { "query": "{{query}}", "fields": ["title^3"] } },
            "filter": [
              { "term": { "tenant_id": "{{tenant_id}}" } },
              { "range": { "price": { "gte": "{{min_price}}", "lte": "{{max_price}}" } } }
            ]
          }
        },
        "from": "{{from}}",
        "size": "{{size}}"
      }
    }
  }

  GET _search/template { "id": "product_search", "params": { ... } }

  Benefits: query logic in cluster, versioned, prevents query injection from raw strings


PATTERN 5: CIRCUIT BREAKER + FALLBACK (WEEK 6 TIE-IN)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Search service wraps ES client with:
    - Timeout: 500ms search, 200ms suggest
    - Circuit breaker: 50% failure rate → open 30s
    - Fallback: degraded search (category browse only) OR cached top queries
    - Never fallback to PG LIKE query under load — makes PG worse

  Bulkhead: separate thread pools for search vs indexing admin APIs


PATTERN 6: CROSS-CLUSTER REPLICATION (DISASTER RECOVERY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Primary domain: us-east-1 (read/write)
  Follower domain: us-west-2 (read-only replica for DR)

  AWS OpenSearch CCR: auto-follow on products-* pattern
  Failover: manual promotion of follower (not automatic — split-brain risk)
  RPO: replication lag (monitor follower checkpoint lag)


PATTERN 7: WARM/HOT TIER (ULTRAWARM ON AWS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Hot: r6g — active indices, full query performance
  UltraWarm: s3-backed, lazy-loaded — 90% storage savings
  Cold: searchable snapshots — infrequent access

  Move indices via ISM policy:
    logs-* > 7 days → warm tier
    logs-* > 30 days → cold storage
```

---

## 6. Failure Modes

```
FAILURE MODE 1: YELLOW CLUSTER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: GET _cluster/health → "status": "yellow"
  Meaning: All primary shards assigned, SOME replica shards unassigned

  Common causes:
  → Single data node with number_of_replicas: 1
    (primary and replica can't sit on same node — allocation rule)
  → Node loss: replica not yet reallocated
  → Disk watermark exceeded on target node (85% low, 90% high, 95% flood)
  → Shard allocation awareness: not enough AZs for replica placement

  Risk level:
    Yellow with replicas=0 on single node: expected in dev
    Yellow in prod with replicas≥1: DEGRADED — no redundancy on affected shards

  Fix:
    Add data node OR reduce replicas temporarily OR free disk
    GET _cluster/allocation/explain { "index": "products", "shard": 0, "primary": false }


FAILURE MODE 2: RED CLUSTER
━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: "status": "red", queries fail or return partial results
  Meaning: One or more PRIMARY shards unassigned

  Common causes:
  → Multiple node failures exceeding replica capacity
  → Corrupt shard — allocation fails repeatedly
  → Split-brain aftermath (see below)
  → Accidental index deletion during incident

  Impact: Data for unassigned shards UNAVAILABLE for read and write

  Fix (urgency order):
    1. Restore from snapshot (AWS automated snapshots — check latest)
    2. If replica exists on surviving node: retry allocation
    3. Last resort: _cluster/reroute allocate_stale_primary (DATA LOSS RISK)
    4. Rebuild from PG (CQRS read model advantage — Week 5)


FAILURE MODE 3: SPLIT BRAIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  What: Two subsets of cluster each believe they are the authoritative cluster
  Result: Divergent writes, index corruption, red cluster when reunited

  Classic cause (pre-7.x): minimum_master_nodes misconfigured
  Modern cause (7.x+): cluster_manager election during network partition
    without proper discovery.seed_hosts / cluster.initial_cluster_manager_nodes

  AWS OpenSearch mitigation:
    Dedicated cluster manager nodes (3 AZ)
    Domain endpoint enforces quorum internally
    Still possible during misconfigured cross-cluster or manual cluster state edits

  Symptoms:
    Two master-eligible nodes both log "elected as master"
    Writes succeed to both partitions — different doc counts per "half"
    Cluster health flaps red/yellow after network heal

  Prevention:
    Odd number of cluster_manager nodes (3 or 5)
    NEVER split cluster_manager across unreliable network without fencing
    Use discovery.zen.minimum_master_nodes equivalent (built-in in 7.x+)

  Recovery:
    1. Isolate minority partition (stop nodes or network partition)
    2. Identify authoritative side (higher term, more shards, or restore from snapshot)
    3. Wipe data on minority nodes, rejoin as fresh nodes
    4. Reindex from PG if write divergence occurred


FAILURE MODE 4: MAPPING EXPLOSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: Cluster state updates take minutes, master GC pauses, indexing rejected
  Error: "Limit of total fields [1000] has been exceeded"
         or "cluster state too large"

  Root cause:
    dynamic: true + high-cardinality field names
    Example: logging raw JSON → each unique key becomes a field
    Example: mapping user_id as text with fielddata → disaster

  Case study pattern:
    App sends: { "metadata": { "user_12345_pref": "dark_mode", ... } }
    → Flattened keys create millions of unique fields

  Fix:
    Immediate: index.mapping.total_fields.limit (raises ceiling — bandaid)
    Proper: strict mapping, flattened type, or reindex with correct schema
    Drop and recreate corrupt index, rebuild from PG/Kafka

  Prevention:
    dynamic: strict on ALL production indices
    index.mapping.total_fields.limit: 2000 (alert at 1500)
    CI test: sample document against mapping validator before deploy


FAILURE MODE 5: HOT SHARD / SKEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: One data node at 100% CPU while others idle, p99 latency spikes
  Cause: Routing hotspot, bad shard key, or time-based index with today's shard absorbing all writes

  Detection:
    GET _cat/shards?v&s=store:desc
    GET _nodes/stats/indices/indexing,index,search

  Fix:
    Re-route with custom routing hash salt
    Increase shards on next index generation
    Separate write-heavy index (logs today) from read-heavy (products)


FAILURE MODE 6: GC STORM / HEAP PRESSURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: P99 search latency 5s+, nodes unresponsive, circuit breakers trip
  Cause: Fielddata loaded on text fields, heavy aggregations, too many segments,
         oversized global ordinals, deep pagination with scroll contexts

  Circuit breakers (auto-trip to protect JVM):
    parent: 95% heap limit
    fielddata: text field sorting (NEVER sort on analyzed text)
    request: single request memory (large aggs)
    accounting: long-lived memory (scroll, PIT)

  Fix:
    Kill scroll/PIT contexts: DELETE _search/scroll/_all
    Cancel tasks: POST _tasks/_cancel?actions=*search*
    Reduce agg complexity, add filters to reduce scope
    Upgrade instance type or reduce shard count


FAILURE MODE 7: CDC LAG → STALE SEARCH (CQRS DRIFT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: User updates product in admin, search shows old title for 5+ minutes
  Cause: Kafka consumer lag, indexer errors, mapping reject, ES bulk queue full

  NOT an ES bug — pipeline bug. But users blame "search is broken."

  Detection:
    Kafka consumer lag metric per indexer group
    Compare PG updated_at max vs ES indexed_at max

  Fix:
    Scale indexer consumers, fix mapping rejections (dead letter queue)
    Temporary: increase refresh_interval doesn't fix lag — fixes visibility only

  Week 5 reminder: PG is truth. Display "last updated" from PG on detail pages;
    search results may lag — set user expectation or block publish until indexed.


FAILURE MODE 8: REINDEX DURING PEAK TRAFFIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Symptom: Search and indexing latency doubles during migration
  Cause: _reindex reads source + writes dest — doubles I/O and heap

  Fix:
    Reindex during maintenance window with throttling:
      POST _reindex?wait_for_completion=false
      { "source": {...}, "dest": {...}, "conflicts": "proceed",
        "slice": { "id": 0, "max": 4 } }  // parallel slices
    Set slices = number of shards for parallelism
    Monitor cluster with reindex throttling: requests_per_second
```

---

## 7. SRE Diagnostic Toolkit

```
CLUSTER HEALTH (RUN FIRST):
━━━━━━━━━━━━━━━━━━━━━━━━━━

  GET _cluster/health?pretty
  GET _cat/health?v
  GET _cluster/stats?pretty

  Key fields:
    status: green | yellow | red
    relocating_shards / initializing_shards / unassigned_shards
    number_of_nodes / number_of_data_nodes


SHARD ALLOCATION:
━━━━━━━━━━━━━━━

  GET _cat/shards?v&s=index,shard,prirep,store:desc
  GET _cat/allocation?v
  GET _cluster/allocation/explain
  {
    "index": "products-v7",
    "shard": 2,
    "primary": true
  }


NODE RESOURCES:
━━━━━━━━━━━━━━━

  GET _cat/nodes?v&h=name,heap.percent,ram.percent,cpu,load_1m,disk.used_percent,master
  GET _nodes/stats/jvm,indices,os,fs?pretty
  GET _nodes/hot_threads

  AWS CloudWatch (OpenSearch):
    ClusterStatus.yellow / .red
    CPUUtilization, JVMMemoryPressure (> 80% sustained = danger)
    FreeStorageSpace (< 20% = act now)
    SearchLatency, IndexingLatency
    KibanaOpenSearchRequests (if using Dashboards)


PENDING TASKS / MASTER HEALTH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  GET _cat/pending_tasks?v
  GET _cluster/state/master_node,version?pretty

  Long pending tasks → cluster state bottleneck, large mapping updates


INDEX-LEVEL:
━━━━━━━━━━━━

  GET _cat/indices?v&s=store.size:desc&health
  GET products-v7/_stats?pretty
  GET products-v7/_segments
  GET products-v7/_settings
  GET products-v7/_mapping

  Segment count per shard: > 100 segments → merge falling behind
  docs.count vs store.size — growth rate tracking


QUERY DEBUGGING:
━━━━━━━━━━━━━━━━

  GET products/_search
  {
    "profile": true,
    "query": { "match": { "title": "headphones" } }
  }

  → Shows time per shard, rewrite chains, collection stats

  GET products/_validate/query?explain=true
  { "query": { "match": { "title": "headphones" } } }

  Explain specific doc score:
  GET products/_explain/doc_123
  { "query": { "match": { "title": "wireless headphones" } } }


SLOW LOGS (ENABLE IN PRODUCTION WITH SAMPLING):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PUT _cluster/settings
  {
    "transient": {
      "index.search.slowlog.threshold.query.warn": "2s",
      "index.search.slowlog.threshold.fetch.warn": "1s",
      "index.indexing.slowlog.threshold.index.warn": "5s"
    }
  }

  AWS: OpenSearch logs → slow logs to CloudWatch Logs


ACTIVE TASKS:
━━━━━━━━━━━━━

  GET _tasks?detailed=true&actions=*search*
  POST _tasks/task_id:node_id/_cancel

  Scroll leak detection:
  GET _nodes/stats/indices/search?filter_path=**.open_contexts


CIRCUIT BREAKER STATUS:
━━━━━━━━━━━━━━━━━━━━━━━

  GET _nodes/stats/breaker?pretty

  tripped count > 0 → investigate heap, aggs, fielddata


AWS CLI (OPENSEARCH):
━━━━━━━━━━━━━━━━━━━━━

  aws opensearch describe-domain --domain-name prod-search
  aws opensearch describe-domain-config --domain-name prod-search
  aws opensearch list-domain-names

  Snapshot restore:
  aws opensearch describe-domain --domain-name prod-search \
    --query 'DomainStatus.SnapshotOptions'

  # Manual snapshot to S3 (register repository first via ES API):
  PUT _snapshot/my-s3-repo/snapshot_20240706
  POST _snapshot/my-s3-repo/snapshot_20240706/_restore
  {
    "indices": "products-v7",
    "ignore_unavailable": true
  }


KAFKA / CDC LAG (INDEXER PIPELINE):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  kafka-consumer-groups.sh --bootstrap-server $MSK \
    --group es-product-indexer --describe

  # LAG column = events behind PG


USEFUL ONE-LINERS:
━━━━━━━━━━━━━━━━━━

  # Count docs in index
  GET products/_count

  # Field existence check
  GET products/_search { "size": 0, "aggs": { "missing_brand": {
    "missing": { "field": "brand" } } } }

  # Top slow queries from slow log (CloudWatch Insights):
  fields @timestamp, message
  | filter message like /took_millis/
  | sort @timestamp desc
  | limit 50
```

---

## 8. Decision Framework

```
WHEN TO ADD ELASTICSEARCH/OPENSEARCH:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌─────────────────────────────────────────────────────────────┐
  │ Do users need full-text search with relevance ranking?       │
  │   No  → PG index, Redis, or application filter may suffice  │
  │   Yes ↓                                                       │
  ├─────────────────────────────────────────────────────────────┤
  │ Is PG FTS + GIN index meeting SLA (< 200ms, current QPS)?   │
  │   Yes → Stay on PG until it isn't — don't pre-optimize       │
  │   No  ↓                                                       │
  ├─────────────────────────────────────────────────────────────┤
  │ Do you need faceted search, complex filters, or aggs on       │
  │ search results (e.g., "show brand counts while searching")? │
  │   Yes → ES/OpenSearch strong fit                              │
  │   No  → Consider lighter options (Meilisearch, Typesense)     │
  │         for simpler relevance + typo tolerance                  │
  ├─────────────────────────────────────────────────────────────┤
  │ Data volume > 50M docs OR > 100 GB search index?              │
  │   Yes → Dedicated search cluster justified                    │
  ├─────────────────────────────────────────────────────────────┤
  │ Already running CQRS with Kafka CDC (Week 5)?                 │
  │   Yes → ES as read model is natural — incremental cost lower  │
  │   No  → Factor in pipeline build: 2-4 engineer-months         │
  └─────────────────────────────────────────────────────────────┘


ELASTICSEARCH vs OPENSEARCH vs ALTERNATIVES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────┬────────────────────────────────────────────────┐
  │ OpenSearch   │ AWS-native, no licensing surprise, FGAC, CCR,  │
  │              │ UltraWarm, OpenSearch Ingestion, good default │
  │              │ if already on AWS                             │
  ├──────────────┼────────────────────────────────────────────────┤
  │ Elasticsearch│ Elastic Cloud, latest features first, proprietary│
  │ (Elastic)    │ ML, enterprise security — license review req  │
  ├──────────────┼────────────────────────────────────────────────┤
  │ Algolia      │ Hosted, best-in-class typo/suggest, $$$ at scale│
  │              │ Use when search IS the product (not infra team) │
  ├──────────────┼────────────────────────────────────────────────┤
  │ Meilisearch/ │ Simpler ops, great DX, smaller scale (< 10M)  │
  │ Typesense    │ Self-host or cloud, less agg complexity       │
  ├──────────────┼────────────────────────────────────────────────┤
  │ PG tsvector  │ < 50M rows, simple search, one DB to operate   │
  └──────────────┴────────────────────────────────────────────────┘


SHARD COUNT QUICK REFERENCE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Data Size     │ Primary Shards │ Notes
  ──────────────┼────────────────┼──────────────────────────────
  < 10 GB       │ 1-2            │ Dev/small prod
  10-100 GB     │ 3-6            │ ~20 GB/shard target
  100 GB-1 TB   │ 6-20           │ Monitor per-shard size
  1-10 TB       │ 20-50          │ ILM, time-based indices
  > 10 TB       │ 50+            │ Dedicated architecture review

  NEVER create index with default 5 shards without calculation.


REPLICA COUNT:
━━━━━━━━━━━━━━

  Min production replicas: 1 (survive single node loss)
  Read-heavy search: 2 replicas (3 copies total) for read scaling
  Cost-constrained: 1 replica + good snapshots + PG rebuild path


REFRESH INTERVAL:
━━━━━━━━━━━━━━━━━

  User-facing search:     1s (default)
  CDC indexer steady:     1s (users expect near-real-time)
  Bulk reindex:           -1 (disable), restore after
  Log ingestion:          5s-30s


QUERY API EXPOSURE:
━━━━━━━━━━━━━━━━━

  Public API: search templates with params — NEVER raw query_string from users
  Internal admin: full DSL OK with auth
  Pagination: search_after + PIT for deep results; from/size for page 1-20 only
```

---

## 9. Incident Scenario

```
INCIDENT BRIEF — 14:32 UTC Tuesday
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are the primary on-call for the e-commerce platform "ShopStream."
Search has been degraded for 35 minutes. Customer support reports
"search returns wrong products" and "new products not appearing."

SYMPTOMS (from dashboards and tickets):
  • OpenSearch cluster status: YELLOW (since 13:58 UTC)
  • Search p99 latency: 850ms (baseline 120ms)
  • Indexing rate dropped 70% at 13:55 UTC
  • Support: "Brand filter shows 0 results for Nike" (was fine yesterday)
  • Product manager: SKU launched 30 min ago not findable in search
  • No recent application deploys to search API
  • Infra change at 13:50 UTC: autoscaled data node pool 6 → 4 nodes
    (cost optimization cron — supposed to scale down off-peak only)

AVAILABLE DATA:

  GET _cluster/health:
  {
    "status": "yellow",
    "number_of_nodes": 7,
    "number_of_data_nodes": 4,
    "unassigned_shards": 12,
    "relocating_shards": 0,
    "active_shards_percent_as_number": 83.3
  }

  GET _cat/shards?v | grep UNASSIGNED (truncated):
  products-v7  2  r  UNASSIGNED
  products-v7  5  r  UNASSIGNED
  products-v7  8  r  UNASSIGNED
  ... (12 replica shards unassigned)

  GET _cat/nodes?v:
  node-1  92  78  45  m  ← cluster_manager
  node-2  88  81  52     ← data, disk 91%
  node-3  45  62  12     ← data, disk 45%
  node-4  41  58  10     ← data, disk 43%
  node-5  OFFLINE since 13:52  ← was data node, terminated by autoscaler
  node-6  OFFLINE since 13:52
  node-7  38  55  8      ← data (newly added? partial scale)

  Indexer consumer lag (Kafka): 847,000 messages (was < 1000)
  Error log from indexer (13:56):
    "mapper_parsing_exception: failed to parse field [price]"

  Recent mapping change (merged 11:00 UTC deploy):
    price changed from "float" to "scaled_float" in template
    products-v7 still has old mapping — products-v8 created but alias NOT swapped

  Sample failed document:
    { "sku": "NK-2024-001", "price": "129.99", "brand": "Nike" }
    (price sent as string from new supplier API integration)

YOUR TASKS (no hand-holding — structure your response as you would in a
real incident doc):
  1. Identify ALL root causes (there is more than one)
  2. Immediate mitigation steps (next 15 minutes)
  3. Customer-facing impact assessment
  4. Fix plan for next 24 hours
  5. Prevention items for post-incident review
```

---

## 10. Expert Analysis

### Root Cause Analysis

```
ROOT CAUSE 1 — AUTOSCALER TERMINATED DATA NODES DURING PEAK (PRIMARY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  At 13:50 UTC, autoscaler reduced data nodes 6 → 4 during active traffic.
  nodes node-5 and node-6 terminated at 13:52.
  12 replica shards became UNASSIGNED → cluster YELLOW at 13:58.
  Remaining nodes absorbed shard primaries but replicas not reallocated
  because: (a) disk on node-2 at 91% — high watermark blocks allocation,
  (b) only 4 data nodes with 12 primary + 12 replica = 24 shard copies,
       insufficient capacity for rack/zone awareness rules.

  Impact: Loss of read scaling (replicas serve search), redundancy gone,
  rebalancing I/O caused latency spike.


ROOT CAUSE 2 — INDEXER MAPPING REJECTION (SECONDARY, USER-VISIBLE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  New supplier integration sends price as string "129.99" not float 129.99.
  Indexer bulk requests fail mapper_parsing_exception.
  Kafka lag 847K → new products (including Nike SKU) not indexed.
  This explains "product not findable" — NOT the yellow cluster alone.

  Partial brand facet failure: indexer poison-pill batch may have caused
  consumer stall; older docs intact but incremental updates stalled.
  Nike filter showing 0: possible bad agg cache OR separate bug — check
  if Nike docs exist: GET products/_count { "query": { "term": { "brand": "Nike" } } }
  If count > 0 but facet 0 → agg cache/query bug. If count 0 → indexing failure.


ROOT CAUSE 3 — INCOMPLETE INDEX MIGRATION (LATENT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  products-v8 created with new scaled_float mapping at 11:00 but alias
  still points to products-v7. Template change doesn't retroactively fix v7.
  Not direct cause of today's incident but blocked clean price migration.


CONTRIBUTING: DISK PRESSURE ON NODE-2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  91% disk → high watermark → replica allocation blocked → stuck yellow
```

### Immediate Mitigation (0–15 Minutes)

```
1. STOP AUTOSCALER DOWNSCALE
   Disable cost cron or set min data nodes = 6 immediately.
   aws autoscaling update-policy / manual scale UP to 6 data nodes.

2. FREE DISK ON NODE-2
   DELETE old indices past retention (logs-2024.05.* if safe).
   OR increase EBS volume size via AWS console (online resize).
   Target: node-2 disk < 85%.

3. FIX INDEXER POISON PILL
   Deploy indexer hotfix: coerce price to float before bulk index.
   OR temporary ingest pipeline:
     PUT _ingest/pipeline/fix_price
     { "processors": [{ "convert": { "field": "price", "type": "float", "ignore_missing": true } }] }
   Skip/reprocess DLQ batch after fix.

4. SCALE INDEXER CONSUMERS
   4 → 8 pods to drain 847K lag once errors stop.

5. COMMUNICATE
   Status page: "Search results may be incomplete for newly added products.
   Browsing and checkout unaffected." (PG is source of truth for cart/checkout)
```

### Customer Impact

```
SEVERITY: SEV-2 (degraded, partial data stale — not full outage)

  • Search latency elevated — poor UX but functional for cached catalog
  • New/updated products missing from search — REVENUE IMPACT on new launches
  • Brand facets potentially wrong — navigation degraded
  • Checkout/detail pages OK if served from PG/Redis (CQRS read path split)
  • Yellow cluster: single node failure away from RED on affected shards
```

### 24-Hour Fix Plan

```
HOUR 0-2:   Restore 6 data nodes, disk cleanup, confirm green/yellow resolved
HOUR 2-4:   Indexer fix deployed, lag draining, validate new SKU searchable
HOUR 4-8:   Complete products-v8 migration:
              - Reindex v7 → v8 with ingest pipeline
              - Validate doc counts and price field types
              - Alias swap products → v8
HOUR 8-24:  Post-incident hardening (see prevention)
            Reconciliation job: compare PG product count vs ES count
            Replay Kafka from known-good offset if any permanent gap
```

### Prevention (Post-Incident Actions)

```
1. Autoscaler guardrails: min nodes = peak baseline, scale-down only if
   CPU < 30% for 30 min AND cluster green AND business hours check

2. Indexer schema validation: JSON schema in CI for CDC documents,
   reject at producer (supplier API) not at ES

3. Dead letter queue + alert on first mapper_parsing_exception

4. Kafka lag alert: > 10,000 messages for 5 min → page

5. Cluster health alert: yellow > 5 min → page (not just red)

6. Disk watermark alert: any node > 80%

7. Mapping changes: mandatory reindex + alias swap runbook in same PR

8. CQRS reconciliation: hourly doc count delta PG vs ES (Week 5 invariant)

9. Game day: simulate node loss + indexer stall quarterly
```

---

## 11. Key Takeaways

```
1. Inverted indexes map terms → documents; they solve a fundamentally different
   problem than B-tree indexes (Week 2). Full-text search at scale requires
   tokenization, BM25 scoring, and a distributed search engine — not SQL LIKE.

2. Elasticsearch/OpenSearch is a near-real-time search layer, not a database.
   Writes are visible after refresh (~1s); updates are delete+insert; use it as
   a CQRS read model with PostgreSQL as source of truth (Week 5).

3. Shard and replica design is permanent and operational: too many shards
   bloat cluster state; too few replicas mean yellow clusters and data risk.
   Size shards to 10–50 GB and keep production replicas ≥ 1.

4. Mapping discipline prevents mapping explosions — dynamic: strict, explicit
   field types, keyword for filters/aggs, text for search. Analyzer changes
   require reindex.

5. Production incidents cluster around allocation (yellow/red), pipeline lag
   (stale search), and heap pressure (bad aggs, scroll leaks). Diagnose with
   _cluster/health, _cat/shards, consumer lag, and _nodes/stats — fix PG→ES
   pipeline before tuning queries.
```

---

## 12. Targeted Reading

```
PRIMARY (SEARCH-SPECIFIC):
━━━━━━━━━━━━━━━━━━━━━━━━━━

  Elasticsearch: The Definitive Guide (deprecated title, still excellent)
    → Ch 1-2: inverted index, analysis, mapping
    → Ch 6: Lucene-based scoring (BM25)
    → Ch 14-16: cluster architecture, shard allocation
    → Free online: elastic.co/guide/en/elasticsearch/guide

  OpenSearch Documentation (AWS-maintained fork docs)
    → opensearch.org/docs/latest/im-index/
    → opensearch.org/docs/latest/query-dsl/
    → opensearch.org/docs/latest/aggregations/
    → opensearch.org/docs/latest/tuning-your-cluster/

  Apache Lucene Core Javadocs — SegmentMerger, BM25Similarity
    → lucene.apache.org (read BM25Similarity source for interview depth)


AWS OPENSEARCH (DEPLOYMENT + OPS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AWS OpenSearch Service Developer Guide
    → docs.aws.amazon.com/opensearch-service/latest/developerguide/
    → Sections: sizing domains, UltraWarm, Cognito/FGAC, automated snapshots
    → "Recommended CloudWatch alarms" page — copy into Terraform

  AWS Blog: "Best practices for Amazon OpenSearch Service"
    → Shard count, dedicated masters, connection pooling


CURRICULUM CROSS-REFERENCES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Week 2 — SQL Deep Dive, Part C: Indexing (B-tree, composite, covering)
    → Contrast directly when explaining inverted vs B-tree

  Week 5 — Database Scaling Patterns, Part 13: CQRS and Polyglot Persistence
    → Part 14: CDC Failure Modes (indexer idempotency, deletes, schema evolution)

  Week 6 — Outbox Pattern and CDC (if present): end-to-end pipeline design

  Week 4 — Sharding: routing concepts parallel ES shard routing


INTERVIEW / DEPTH ON DEMAND:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  "BM25 at 123" — plg.uwaterloo.ca (~2011) — original BM25 paper context
  Elastic blog: "Fundamentals of Apache Lucene" series
  Elastic blog: "Elasticsearch from the bottom up" (historical but lucid)

  Skip: reading DDIA cover-to-cover for this topic — read DDIA Ch 3
  (storage/indexing) only if you want OLTP vs search engine contrast in one place.
```

---

## Appendix A: AWS OpenSearch Domain Architecture

```
MANAGED SERVICE LAYERING:
━━━━━━━━━━━━━━━━━━━━━━━━━

  Your application
        │
        ▼ (HTTPS, SigV4 auth)
  ┌─────────────────────────────────────┐
  │  VPC endpoint / public domain endpoint │
  └─────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────┐
  │  AWS OpenSearch Service (managed)      │
  │  ├── Data nodes (your instance type) │
  │  ├── Optional dedicated cluster mgrs │
  │  ├── Optional UltraWarm / cold        │
  │  └── Automated snapshots → S3         │
  └─────────────────────────────────────┘
        │
        ▼
  EBS gp3 / io1 volumes per data node

DOMAIN CONFIGURATION CHECKLIST (PRODUCTION):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [ ] VPC-only access (no public endpoint)
  [ ] Fine-grained access control (FGAC) enabled
  [ ] Encryption at rest (KMS CMK)
  [ ] Node-to-node encryption
  [ ] Minimum 3 AZ for zone awareness (if multi-AZ)
  [ ] Dedicated cluster manager nodes (3 × m6g.large.search minimum for prod)
  [ ] Automated snapshot hour configured (off-peak UTC)
  [ ] CloudWatch alarms: ClusterStatus, JVMMemoryPressure, FreeStorageSpace
  [ ] Log publishing: slow logs, error logs, audit logs → CloudWatch
  [ ] Access policy: IAM role for indexer, IAM role for search API, deny *

INSTANCE SIZING WORKED EXAMPLE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Requirements:
    400 GB index data, 1500 search QPS, 500 docs/sec indexing
    p99 search < 200ms, 1 replica for HA

  Step 1: Shards = 400 GB / 30 GB = 14 → round to 16 primary shards
  Step 2: Shard copies = 16 × 2 (1 replica) = 32 total shards
  Step 3: Heap need ~ 32 shards / 20 shards per GB heap → 2 GB min heap
          Real workload: aggs + sorting → 16 GB heap comfortable
  Step 4: Data node RAM = 32 GB (50% heap rule) → r6g.xlarge (32 GB)
  Step 5: Nodes = 32 shards / ~4 shards per node target = 8 data nodes
          (adjust based on CPU profiling — search is CPU-heavy)

  Step 6: 3 dedicated cluster managers (never co-locate with heavy data on small clusters)

  Validate with load test before prod cutover — math is starting point only.


CONNECTION FROM EKS (IRSA PATTERN):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ServiceAccount → IAM role (es:ESHttpGet, ESHttpPost on domain ARN)
  OpenSearch Python client:

    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth

    auth = AWS4Auth(creds.access_key, creds.secret_key, region, 'es', session_token=...)
    client = OpenSearch(
        hosts=[{'host': domain_endpoint, 'port': 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
        max_retries=3,
        retry_on_timeout=True
    )

  Connection pooling: one client per process, NOT per request
  Bulk thread pool separate from search thread pool in application
```

---

## Appendix B: Advanced Query DSL Patterns

```json
GET products/_search
{
  "query": {
    "dis_max": {
      "queries": [
        { "match_phrase": { "title": { "query": "wireless headphones", "boost": 3 } } },
        { "match": { "title": { "query": "wireless headphones", "fuzziness": "AUTO" } } },
        { "match": { "description": "wireless headphones" } }
      ],
      "tie_breaker": 0.3
    }
  }
}
```

```
DIS_MAX: best matching subquery wins; tie_breaker adds fraction of other matches
  → Better than bool should for "title exact phrase OR fuzzy title OR description"

FUZZINESS AUTO:
  0 edits for 1-2 char terms, 1 edit for 3-5 chars, 2 edits for 6+ chars
  Expensive on large fields — restrict to title, not description body

MORE_LIKE_THIS (recommendations):
  GET products/_search {
    "query": {
      "more_like_this": {
        "fields": ["title", "description"],
        "like": [{ "_id": "prod_123" }],
        "min_term_freq": 1,
        "max_query_terms": 25
      }
    }
  }

PERCOLATE (reverse search — query stored, docs matched against it):
  Use case: "alert me when new listing matches saved search"
  Index stores registered queries; new doc percolates against query index
  Heavy memory — niche but powerful for notification systems
```

---

## Appendix C: Interview Rapid-Fire

```
Q: Difference between filter and query context?
A: Query context scores (BM25); filter context yes/no bitset, cached, no score.
   Production: structured predicates in filter, text match in must/should.

Q: Why not update Elasticsearch documents in place?
A: Lucene segments immutable. Update = tombstone old + insert new. High update
   rate causes merge pressure. Prefer append-only with periodic reindex for
   heavy mutators, or design denormalized docs that change infrequently.

Q: How does Elasticsearch handle a node failure with replicas=1?
A: Cluster manager detects node loss, promotes replica to primary on surviving
   node, allocates new replica copy when replacement node joins. Brief yellow
   during reallocation. Unassigned primary with no replica = red, data loss
   risk until snapshot restore.

Q: When would you use PG instead of ES for search?
A: < 50M docs, simple tsquery, team lacks ES ops capacity, strong transactional
   coupling (search within same txn as write — rare). ES when relevance tuning,
   facets, scale, or CQRS separation justify operational cost.

Q: Explain near-real-time in one sentence.
A: Documents are searchable after refresh flushes the in-memory buffer to a
   new segment (~1s default), not at the moment of the index API 201 response.

Q: What causes mapping explosion and how do you prevent it?
A: Dynamic mapping of high-cardinality keys (UUID field names, unbounded JSON).
   Prevent with dynamic:strict, flattened type for semi-structured data, and
   total_fields limit with alerting.
```

---

*End of Week 7: Search Systems and Inverted Indexes*

