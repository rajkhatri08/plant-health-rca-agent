"""Code shared by app/ and the builder side (eval/), kept outside both so the import
walls hold (eval/LEAKAGE.md): app/ never imports eval/, and nothing here is agent-visible."""