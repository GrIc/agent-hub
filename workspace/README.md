# Workspace

Symlink or copy your codebase here:

```bash
# Option 1: Symlink (recommended)
ln -s /path/to/your/code workspace

# Option 2: Copy
cp -r /path/to/your/code workspace
```

Agent Hub will scan all files in this directory to build the RAG index.

Configure which file extensions to include in `config.yaml` → `rag.extensions`.