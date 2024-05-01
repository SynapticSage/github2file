import os
import sys
import requests
import zipfile
import io
import ast
import logging
import argparse
import fnmatch
import time

file_extension_dict = {
        'python': ['.py'],
        'py': ['.py'],
        'ipython': ['.ipynb'],
        'ipynb': ['.ipynb'],
        'go': ['.go'],
        'js': ['.js'],
        'html': ['.html'],
        'mojo': ['.mojo'],
        'java': ['.java'],
        'c': ['.c','.h'],
        'cpp': ['.cpp','.h','.hpp'],
        'c++': ['.cpp','.h','.hpp'],
        'csharp': ['.cs'],
        'ruby': ['.rb'],
        'mojo': ['.mojo'],
        'javascript': ['.js'],
        'markdown': ['.md', '.markdown', '.mdx'],
        'md': ['.md'],
        'shell': ['.sh'],
        'bash': ['.sh'],
        'zsh': ['.sh'],
}

def is_file_type(file_path, file_languages:list):
    """Check if the file has any of the specified file extensions."""
    is_ft = any(file_path.endswith(ext) for file_language in file_languages for
        ext in file_extension_dict[file_language.replace('.','')])
    if not is_ft:
        logging.debug(f"Skipping file: {file_path}")
    return is_ft

def is_likely_useful_file(file_path:str, lang:str, args:argparse.Namespace)->bool:
    """Determine if the file is likely to be useful by excluding certain
    directories and specific file types."""
    excluded_dirs = args.excluded_dirs
    utility_or_config_files = []
    github_workflow_or_docs = [".github", ".gitignore", "LICENSE", "README"]

    if lang == "python" or lang == "mojo":
        excluded_dirs.append("__pycache__")
        utility_or_config_files.extend(["hubconf.py", "setup.py"])
        github_workflow_or_docs.extend(["stale.py", "gen-card-", "write_model_card"])
    elif lang == "go":
        excluded_dirs.append("vendor")
        utility_or_config_files.extend(["go.mod", "go.sum", "Makefile"])
    elif lang == "js":
        excluded_dirs.extend(["node_modules", "dist", "build"])
        utility_or_config_files.extend(["package.json", "package-lock.json", "webpack.config.js"])
    elif lang == "html":
        excluded_dirs.extend(["css", "js", "images", "fonts"])

    if any((part.startswith('.') and not part.startswith('..') and part != '.' and part != '..')
        for part in file_path.split('/')):
        logging.debug(f"Skipping hidden file: {file_path}")
        return False
    if 'test' in file_path.lower():
        logging.debug(f"Skipping test file: {file_path}")
        return False
    for excluded_dir in excluded_dirs:
        if f"/{excluded_dir}/" in file_path or file_path.startswith(excluded_dir + "/"):
            logging.debug(f"Skipping excluded directory: {file_path}")
            return False
    for file_name in utility_or_config_files:
        if file_name in file_path:
            logging.debug(f"Skipping utility or config file: {file_path}")
            return False
    for doc_file in github_workflow_or_docs:
        doc_file_check = (doc_file in file_path if not doc_file.startswith(".") else
                 doc_file in os.path.basename(file_path))
        if doc_file_check:
            logging.debug(f"Skipping GitHub workflow or documentation file: {file_path}")
            return False
    return True

def is_test_file(file_content, lang):
    """Determine if the file content suggests it is a test file."""
    test_indicators = []
    if lang == "python" or lang == "mojo":
        test_indicators = ["import unittest", "import pytest", "from unittest", "from pytest"]
    elif lang == "go":
        test_indicators = ["import testing", "func Test"]
    elif lang == "js":
        test_indicators = ["describe(", "it(", "test(", "expect(", "jest", "mocha"]
    return any(indicator in file_content for indicator in test_indicators)

def has_sufficient_content(file_content, min_line_count=10):
    """Check if the file has a minimum number of substantive lines."""
    lines = [line for line in file_content.split('\n') if line.strip() and not line.strip().startswith(('#', '//'))]
    return len(lines) >= min_line_count

def remove_comments_and_docstrings(source):
    """Remove comments and docstrings from the Python source code."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body = node.body[1:]  # Remove docstring
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
            node.value.s = ""  # Remove comments
    return ast.unparse(tree)

def extract_git_folder(folder:str)->str|None:
    """ Extract the git folder name from the folder path 
    We must search from the lower child folder up to the parent folder
    looking for .git
    """
    while folder:
        if '.git' in os.listdir(folder):
            return os.path.basename(folder)
        folder = os.path.dirname(folder)
    return None


def should_exclude_file(file_path, exclude_patterns):
    """Check if the file path matches any of the exclude patterns."""
    answer = any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns)
    if answer:
        logging.debug(f"Excluding file: {file_path}")
    return answer

def download_repo(args):
    """Download and process files from a GitHub repository."""
    download_url = f"{args.repo_url}/archive/refs/heads/{args.branch_or_tag}.zip"

    print(download_url)
    response = requests.get(download_url)

    if response.status_code == 200:
        zip_file = zipfile.ZipFile(io.BytesIO(response.content))
        process_zip_file_object(zip_file, args)
    else:
        print(f"Failed to download the repository. Status code: {response.status_code}")
        sys.exit(1)

def process_zip_file(args):
    """Process files from a local .zip file."""
    with zipfile.ZipFile(args.zip_file, 'r') as zip_file:
        process_zip_file_object(zip_file, args)

def process_zip_file_object(zip_file, args):
    """Process files from a local .zip file."""
    file_extensions = [f".{lang}" for lang in args.lang]
    with open(args.output_file, "w", encoding="utf-8") as outfile:
        for file_path in zip_file.namelist():
            if (file_path.endswith("/")
                or not is_file_type(file_path, args.lang)
                or not any(is_likely_useful_file(file_path, lang, args) for lang in args.lang)
                or should_exclude_file(file_path, args.exclude)):
                continue

            if args.include:
                confirm = any(include in file_path for include in args.include)
                if not confirm:
                    logging.debug(f"Skipping file: {file_path}")
                    continue

            file_content = zip_file.read(file_path).decode("utf-8")

            if any(is_test_file(file_content, lang) for lang in args.lang) or not has_sufficient_content(file_content):
                continue
            if "python" in args.lang and not args.keep_comments:
                try:
                    file_content = remove_comments_and_docstrings(file_content)
                except SyntaxError:
                    continue

            comment_prefix = "// " if any(lang in ["go", "js"] for lang in args.lang) else "# "
            outfile.write(f"{comment_prefix}File: {file_path}\n")
            outfile.write(file_content)
            outfile.write("\n\n")


def process_folder(args):
    """Process files from a local folder."""
    for root, _, files in os.walk(args.folder):
        for file in files:
            file_path = os.path.join(root, file)
            if (not is_file_type(file_path, args.lang)
                or not any(is_likely_useful_file(file_path, lang, args) for lang in args.lang)
                or should_exclude_file(file_path, args.exclude)):
                continue

            if args.include:
                confirm = any(include in file_path for include in args.include)
                if not confirm:
                    logging.debug(f"Skipping file: {file_path}")
                    continue

            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()

            if any(is_test_file(file_content, lang) for lang in args.lang) or not has_sufficient_content(file_content):
                continue
            if "python" in args.lang and not args.keep_comments:
                try:
                    file_content = remove_comments_and_docstrings(file_content)
                except SyntaxError:
                    continue

            with open(args.output_file, 'a', encoding='utf-8') as outfile:
                comment_prefix = "// " if any(lang in ["go", "js"] for lang in args.lang) else "# "
                outfile.write(f"{comment_prefix}File: {file_path}\n")
                outfile.write(file_content)
                outfile.write("\n\n")

def create_argument_parser():
    parser = argparse.ArgumentParser(description='Download and process files from a GitHub repository.')
    parser.add_argument('--zip_file', type=str, help='Path to the local .zip file')
    parser.add_argument('--folder', type=str, help='Path to the local folder')
    parser.add_argument('--lang', type=str, default='python', help='The programming language(s) of the repository (comma-separated)')
    parser.add_argument('--keep-comments', action='store_true', help='Keep comments and docstrings in the source code (only applicable for Python)')
    parser.add_argument('--branch_or_tag', type=str, help='The branch or tag of the repository to download', default="master")
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--include', type=str, help='Comma-separated list of subfolders/patterns to focus on')
    parser.add_argument('--exclude', type=str, help='Comma-separated list of file patterns to exclude')
    parser.add_argument('--excluded_dirs', type=str, help='Comma-separated list of directories to exclude',
                        default="docs,examples,tests,test,scripts,utils,benchmarks")
    parser.add_argument('repo_url', type=str, help='The URL of the GitHub repository',
                        default="", nargs='?')
    return parser

def check_for_include_override(include_list, exclude_list):
    """Check if any of the exclude_list are overridden by the include_list"""
    checks = {include:(include in exclude_list) for include in include_list}
    if any(checks.values()):
        # pop the excluded_dirs if it is included in the include list
        for include, value in checks.items():
            if value:
                logging.debug(f"Removing {include} from the exclude list")
                exclude_list.remove(include)

def main(args=None):
    parser = create_argument_parser()
    args = parser.parse_args(args)
    args.lang = [lang.strip() for lang in args.lang.split(',')]
    if args.excluded_dirs:
        args.excluded_dirs = [subfolder.strip() for subfolder in args.excluded_dirs.split(',')]
    if args.include:
        args.include = [subfolder.strip() for subfolder in args.include.split(',')]
        check_for_include_override(args.include, args.exclude)
        check_for_include_override(args.include, args.excluded_dirs)
    else:
        args.include = []
    if args.exclude:
        args.exclude = [pattern.strip() for pattern in args.exclude.split(',')]
    else:
        args.exclude = []

    if args.debug:
        print("Debug logging enabled")
        # Enable debug logging
        logging.basicConfig(level=logging.DEBUG)
        logging.debug("Debug logging enabled")
        logging.debug(f"Arguments: {args}")
        input("Press Enter to continue...")
    else:
        # Enable info logging
        logging.basicConfig(level=logging.INFO)

    try:
        if args.repo_url:
            args.output_file = f"{args.repo_url.split('/')[-1]}_{','.join(args.lang)}.txt"
            download_repo(args)
        elif args.zip_file:
            args.output_file = f"{os.path.splitext(os.path.basename(args.zip_file))[0]}_{','.join(args.lang)}.txt"
            process_zip_file(args)
        elif args.folder:
            # Find the git repo name from the folder path
            gitfolder = extract_git_folder(args.folder)
            check_for_include_override(args.folder.split('/'), args.exclude)
            check_for_include_override(args.folder.split('/'), args.excluded_dirs)
            if not gitfolder:
                print("No git folder found in the path")
                sys.exit(1)
            args.output_file = f"{gitfolder}_{','.join(args.lang)}.txt"
            process_folder(args)
        else:
            parser.print_help()
            sys.exit(1)

        if os.path.exists(args.output_file):
            print(f"Combined {', '.join(args.lang).capitalize()} source code saved to {args.output_file}")
        else:
            print("No source code found to save -- check the input arguments")

    except argparse.ArgumentError as e:
        print(str(e))
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()


