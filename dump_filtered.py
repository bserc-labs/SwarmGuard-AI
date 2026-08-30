import os

def dump_files(root_dir, out_file):
    with open(out_file, 'w') as out:
        for dirpath, dirs, files in os.walk(root_dir):
            if any(exclude in dirpath for exclude in ['node_modules', 'venv', '.git', '__pycache__', 'dist', 'frontend/src/components/ui', '.pytest_cache']):
                continue
            for f in sorted(files):
                if f.endswith(('.db', '.pyc', '.png', '.jpg', '.ico', '.html', '.css', 'package-lock.json', '.svg', '.json')):
                    if f not in ['package.json', 'components.json', 'tsconfig.json']:
                        continue
                if 'package-lock' in f:
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
                    pass

dump_files('.', 'project_dump_filtered.txt')
