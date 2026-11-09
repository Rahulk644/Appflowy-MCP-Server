# Disposable CRDT fixtures

`database-0.20.5.bin` is an AppFlowy database `doc_state` captured from this
repository's disposable self-hosted integration suite. It contains generated
database/row IDs, default fields, and the test text “MCP integration row”. It
contains no real account credentials, user workspace content, or Cloud tokens.

Source deployment: first-party self-host repository commit
`0796497ebe36d569734fb8eb559f28264d86605c`, Cloud 0.20.5 image digest
`sha256:4c45a647ae892783afdc8af175c9f2e75d54085a47e62aea1a347a562e0345f3`.

`scripts/check_collab.py` verifies decoding, field rename and row-order removal,
and convergence after applying the incremental update to another document.

Both pycrdt 0.13.0 and 0.14.1 pass this newly captured fixture. It does **not**
reproduce the historical regression on other databases. The supported runtime pin
remains 0.13.0 until a representative failing historical fixture and a broader
matrix establish a safe upgrade. Decode failures raise `CollabDecodeError` before
any mutation is sent; an undecodable snapshot is never replaced by an empty Doc.
