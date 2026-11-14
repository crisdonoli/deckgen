import os


def _uploaded_dir_name(files):
    for file_info in files:
        rel_path = file_info["filename"].replace("\\", "/")
        rel_path = os.path.normpath(rel_path).lstrip("/")
        if os.sep in rel_path:
            return rel_path.split(os.sep)[0]
    return "export"


def save_uploaded_export(files, export_dir):
    saved = 0
    for file_info in files:
        rel_path = file_info["filename"].replace("\\", "/")
        rel_path = os.path.normpath(rel_path).lstrip("/")
        if not rel_path or rel_path.startswith(".."):
            continue
        dest_path = os.path.join(export_dir, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(file_info["body"])
        saved += 1
    return saved


def resolve_export_dir(root):
    faces = ("fronts", "backs", "pdfs")

    def has_direct_pdfs(path):
        return any(f.lower().endswith(".pdf") for f in os.listdir(path))

    def is_valid_export(path):
        if not os.path.isdir(path):
            return False
        if any(os.path.isdir(os.path.join(path, face)) for face in faces):
            return True
        return has_direct_pdfs(path)

    candidates = []
    if is_valid_export(root):
        candidates.append((root, 0, has_direct_pdfs(root)))
    for entry in os.listdir(root):
        entry_path = os.path.join(root, entry)
        if is_valid_export(entry_path):
            depth = len(os.path.relpath(entry_path, root).split(os.sep))
            candidates.append((entry_path, depth, has_direct_pdfs(entry_path)))

    if not candidates:
        raise ValueError("no PDFs found in uploaded directory")

    if len(candidates) == 1:
        return candidates[0][0]

    max_depth = max(c[1] for c in candidates)
    deepest = [c for c in candidates if c[1] == max_depth]
    pdf_deepest = [c for c in deepest if c[2]]
    if pdf_deepest:
        return pdf_deepest[0][0]
    return deepest[0][0]
