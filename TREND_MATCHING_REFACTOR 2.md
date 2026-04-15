# TREND_MATCHING_REFACTOR.md
## Bluesky Post → Twitter Trend Matching: Scaling Refactor Spec

---

### Problem

The current `post_trend_matching.py` runs a full linear scan of all trending
topics for every post. This is O(posts × topics). At 1M posts and 100K+ topic
records, this is computationally infeasible — estimated runtime is multiple days.

The logic is correct. The architecture is wrong. This document specifies the
exact replacement architecture.

---

### Core Principle: Invert the Problem

**Current approach:** For each post, scan all topics.
**New approach:** Build an index over all topics once. Each post does a single
fast lookup against that index.

This changes the complexity from O(posts × topics) to O(topics) for index
build + O(posts × tokens_per_post) for matching — roughly 3-4 orders of
magnitude faster.

---

### Three-Stage Index Architecture

The existing pipeline has three match stages. Each maps to a specific index type.
Do not collapse them — keep all three stages, just replace the inner loop with
an index lookup.

---

#### Stage 1: Exact / Token Match → Inverted Index

**Replace:** `if topic_string in post_text` full scan

**With:** A pre-built dict mapping every token from every topic to the list of
topics containing that token.

```python
from collections import defaultdict

# Build once before processing any posts
topic_token_index = defaultdict(list)
for topic_id, topic_text in topics.items():
    for token in tokenize(topic_text):  # use existing tokenize logic
        topic_token_index[token].append(topic_id)

# Per post — replaces the full scan
candidate_topic_ids = set()
for token in tokenize(post_text):
    candidate_topic_ids.update(topic_token_index.get(token, []))
```

**Result:** Each post touches only the topics that share at least one token
with the post. For most posts this is 0-50 candidates, not 100K.

---

#### Stage 2: Fuzzy Match → TF-IDF Sparse Index

**Replace:** `fuzzywuzzy` / `rapidfuzz` full scan over all topics

**With:** sklearn `TfidfVectorizer` + `linear_kernel` cosine similarity.
Build the TF-IDF matrix over all topic strings once. Query it per post with
a single matrix multiply.

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
import numpy as np

# Build once
vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 3))
topic_texts = list(topics.values())
topic_matrix = vectorizer.fit_transform(topic_texts)  # shape: (n_topics, n_features)

# Per post
def fuzzy_match_tfidf(post_text, top_k=5, threshold=0.25):
    post_vec = vectorizer.transform([post_text])
    scores = linear_kernel(post_vec, topic_matrix).flatten()
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [
        (topic_texts[i], float(scores[i]))
        for i in top_indices
        if scores[i] >= threshold
    ]
```

**Why char_wb ngrams:** Works well for partial string matches and hashtags
without needing exact tokenization. Adjust ngram_range if results are poor.

**Result:** Single vectorized operation per post instead of 100K string
comparisons. Scales to 1M posts in minutes.

---

#### Stage 3: Semantic Match → FAISS Approximate Nearest Neighbor

**Replace:** `sentence_transformers` encode + cosine similarity full scan

**With:** FAISS IndexFlatIP (inner product, equivalent to cosine on normalized
vectors). Embed all topics once. Each post query is a single FAISS search call.

```python
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')  # use existing model if different

# Build once — embed all topics
topic_texts = list(topics.values())
topic_embeddings = model.encode(topic_texts, batch_size=256, show_progress_bar=True)
topic_embeddings = topic_embeddings.astype('float32')
faiss.normalize_L2(topic_embeddings)

dimension = topic_embeddings.shape[1]
faiss_index = faiss.IndexFlatIP(dimension)
faiss_index.add(topic_embeddings)

# Per post
def semantic_match_faiss(post_text, top_k=5, threshold=0.60):
    embedding = model.encode([post_text]).astype('float32')
    faiss.normalize_L2(embedding)
    distances, indices = faiss_index.search(embedding, top_k)
    return [
        (topic_texts[idx], float(dist))
        for dist, idx in zip(distances[0], indices[0])
        if dist >= threshold and idx != -1
    ]
```

**FAISS installation:**
```bash
pip install faiss-cpu   # CPU only — sufficient for this use case
# or
pip install faiss-gpu   # if CUDA GPU is available
```

**Result:** Each post semantic query takes ~1ms regardless of topic count.
1M posts = ~17 minutes for semantic stage alone, not days.

---

### Index Lifecycle

All three indexes must be built **once before the post loop starts**, not inside
the loop. The build cost is paid once per pipeline run.

```
pipeline run start
    │
    ├── load all trending topics into memory
    ├── build token inverted index          (Stage 1)
    ├── fit TF-IDF vectorizer + matrix      (Stage 2)
    ├── embed topics + build FAISS index    (Stage 3, slowest — minutes)
    │
    └── for each post:                      (fast from here)
            ├── Stage 1: token lookup
            ├── Stage 2: TF-IDF query       (only if Stage 1 < threshold)
            └── Stage 3: FAISS query        (only if Stage 2 < threshold)
```

**Important:** Stage 2 and Stage 3 should only run if Stage 1 did not find a
high-confidence match. This cascade keeps the average cost per post low.

---

### Index Persistence (Optional but Recommended for 1M Run)

Building the FAISS index takes a few minutes. If the pipeline restarts mid-run,
you don't want to rebuild it. Persist and reload:

```python
import pickle, faiss

# Save
faiss.write_index(faiss_index, "data/state/trend_faiss.index")
with open("data/state/trend_tfidf.pkl", "wb") as f:
    pickle.dump((vectorizer, topic_matrix, topic_texts), f)

# Load on restart
faiss_index = faiss.read_index("data/state/trend_faiss.index")
with open("data/state/trend_tfidf.pkl", "rb") as f:
    vectorizer, topic_matrix, topic_texts = pickle.load(f)
```

---

### Output Schema

Do not change the output schema. The refactored function must return the same
structure the rest of the pipeline expects. The only thing changing is how
matches are found, not what gets written downstream.

---

### What NOT to Change

- Do not change the matching thresholds (keep existing values)
- Do not change the output format or field names
- Do not change how results are written to disk or Snowflake
- Do not change the tokenization logic — reuse whatever exists
- Do not remove any of the three stages — all three must remain

---

### Dependencies to Add to requirements.txt

```
faiss-cpu>=1.7.4
scikit-learn>=1.3.0
```

`sentence_transformers` should already be present. If not, add it too.

---

### Expected Performance After Refactor

| Stage | Before | After |
|---|---|---|
| Exact/token | O(posts × topics) — days | O(posts × tokens) — minutes |
| Fuzzy | O(posts × topics) — days | O(posts) vectorized — minutes |
| Semantic | O(posts × topics) — days | O(posts) FAISS — ~17 min for 1M |
| **Total 1M posts** | **Infeasible** | **~1-2 hours** |