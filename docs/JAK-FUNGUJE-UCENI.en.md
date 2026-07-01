# How the assistant "knows" our data

An explanation for a non-technical audience (management, users) and as defense material. It answers the question everyone asks: *"How do you train the model on our data?"*

> 🇨🇿 Česky: [JAK-FUNGUJE-UCENI.md](JAK-FUNGUJE-UCENI.md)

---

## Short answer

The model is **not retrained**. Instead, we continuously make our documents available to it so that, for every answer, it works with them as if it knew them — and **always cites the source**. This method is called **RAG** (retrieval-augmented generation). The knowledge does not live "hidden inside the model" but in a searchable base that we keep as a **live mirror of the company's files**.

## Analogy

The language model (`llama3.1`) is like a **smart new colleague**: excellent at the language and at reasoning, but it has **never seen our documents**.

- "Teaching it" does **not** mean sending it to a long training course to memorise everything permanently — that is *fine-tuning*: expensive, slow, and quickly outdated.
- For us, "teaching it" means handing it the **right pages** from our documentation before each answer and saying: *"Answer only from this, and state where you got it."*
- And crucially: we keep its **reference manual up to date**. That continuous updating is the real "learning".

---

## How it works — two phases

### Phase 1: Filling the base (runs automatically in the background)

1. **Folder watching** — the system watches the configured network paths and detects what was added, changed or removed.
2. **Reading + parsing** — extracts text from DOCX/XLSX/PDF (OCR for scanned PDFs, preserving row/column relations in tables).
3. **Chunking** — splits each document into smaller overlapping pieces so a specific paragraph can be found, not just the whole file.
4. **Embedding** — each chunk is turned into a vector (a list of numbers capturing the text's *meaning*). Similar meaning → close vectors.
5. **Storage** — vector + original text + source reference (+ permissions in future) are stored in the vector database.

**Result:** when you add a new document, it becomes part of the knowledge base within minutes — **no training, no IT intervention**.

### Phase 2: Answering a query

1. The question is **also turned into a vector**.
2. The system finds the **most similar chunks** in the base (by meaning and by exact terms — e.g. IP addresses or codes).
3. Those chunks are given to the model as **context**, with the instruction *"answer only from this, cite the source, and if the answer isn't there, say so"*.
4. The model generates an answer **from the provided context** and attaches the sources.

So the model "knows" our data because we hand it to it at that moment — not because it has it permanently memorised.

---

## What the "long-term learning" is

Two things, both **without retraining the model**:

- **Freshness of the base** — automatic mirroring of files: added/changed/deleted documents propagate into the base. The system "learns" from every documentation change on its own.
- **Feedback** — answer ratings (👍/👎) are collected and used to improve *what and how the system searches*, and to flag documents for review.

---

## And real model fine-tuning?

Only as a **deliberate, separate step** — never automatic. It could make sense for the company's answer **style and tone**. For **facts from documents it is unsuitable**, because facts change faster than the model could be trained, source traceability (audit) would be lost, and training on unverified data degrades quality.

So: **facts = RAG**, fine-tuning only later and only supervised.

---

See: [OPONENTURA.md](OPONENTURA.md) (decisions & risks), [README.en.md](../README.en.md) (overview), [BUILD.en.md](BUILD.en.md) (build the system).
