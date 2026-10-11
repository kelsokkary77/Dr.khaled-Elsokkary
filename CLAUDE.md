# Project rules

## PDFs: always convert to Markdown first

Whenever the user attaches or mentions a PDF file, convert it to Markdown with
[MarkItDown](https://github.com/microsoft/markitdown) before reading or analysing it.
Do not read the raw PDF directly.

```bash
markitdown "path/to/file.pdf" -o "<scratchpad>/file.md"
```

- Write the `.md` output to the scratchpad directory, not into the repo, unless the user asks to keep it.
- Read the `.md` file, then answer from it.
- If `markitdown` is missing, install it: `pip install -q 'markitdown[pdf]'`.
- If the output is empty or garbled (likely a scanned PDF with no text layer), tell the user. Then fall back to OCR or the `docling-documents` skill.
- Tell the user in one line that you converted the PDF with MarkItDown.
