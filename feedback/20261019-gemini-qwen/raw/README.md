# Complete original experiment traces

Download: **[raw-traces-20261019T050853Z](https://github.com/jh-han-wk/AS-all/releases/tag/raw-traces-20261019T050853Z)**

Contains 161,822 original files (10,439,724,817 bytes) from all 23,012 first-pass cases plus all 710 supplemental attempts, without outcome filtering. All captured full requests/responses, benchmark records, semantic traces, case/result/claim files are included.

All file contents are preserved byte for byte. No files were redacted. Configured credentials were absent; all credential-shaped heuristic matches were verified as Gemini thoughtSignature fields. Path-shaped experimental text is preserved under the explicit request to publish complete original records.

Download every release asset into one directory, run `sha256sum -c SHA256SUMS`, then use the reassemble/extract commands in ARCHIVES.json. FILE_MANIFEST.json.gz contains all per-file SHA-256 values. FINAL_VIEW.json.gz maps the final 23,012 cases to their original or supplemental attempt. The complete archives keep both attempts, including persistent errors.

RELEASE.json lists direct download URLs, part sizes and SHA-256 values. All remote asset digests were verified after upload. Original experiment source and server files are unchanged.
