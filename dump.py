import os

def dump_files(root_dir, out_file):
    with open(out_file, 'w') as out:
        for dirpath, dirs, files in os.walk(root_dir):
            if any(exclude in dirpath for exclude in ['node_modules', 'venv', '.git', '__pycache__', 'dist']):
                continue
            for f in sorted(files):
                if f.endswith('.db') or f.endswith('.pyc') or f.endswith('.png') or f.endswith('.jpg') or f.endswith('.ico') or f.endswith('.html') or f.endswith('.css'):
                    continue
                file_path = os.path.join(dirpath, f)
                try:
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        content = infile.read()
                        out.write(f"\n{'='*80}\n")
                        out.write(f"FILE: {file_path}\n")
                        out.write(f"{'='*80}\n")
                        out.write(content)
                        out.write("\n")
                except Exception as e:
                    out.write(f"\nError reading {file_path}: {e}\n")

dump_files('.', 'project_dump.txt')
