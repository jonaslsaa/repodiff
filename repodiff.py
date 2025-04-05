#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path
import tempfile
import pyperclip
import difflib
from typing import List, Set, Tuple, Optional

# Rich for pretty terminal UI
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich import box
from rich.prompt import Confirm
from rich.table import Table

# For interactive selection
import questionary
from questionary import Style

# Initialize rich console
console = Console()

# Custom style for questionary
custom_style = Style([
    ('qmark', 'fg:ansigreen bold'),
    ('question', 'fg:ansiyellow bold'),
    ('answered', 'fg:ansigreen bold'),
    ('pointer', 'fg:ansimagenta bold'),
    ('highlighted', 'fg:ansimagenta bold'),
    ('selected', 'fg:ansigreen'),
    ('separator', 'fg:ansiblack'),
    ('instruction', 'fg:ansiblack'),
    ('text', 'fg:ansiwhite'),
    ('disabled', 'fg:ansiblack'),
])

def is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True
    except subprocess.CalledProcessError:
        return False

def _extract_status_and_path_from_line(line: str) -> Tuple[str, str]:
    """
    Extract the status code and file path from a git status --porcelain line.
    Returns a tuple (status, file_path).
    """
    status = line[:2]
    file_path = line[2:].lstrip()
    return status, file_path

def get_changed_files() -> Tuple[List[str], Set[str], Set[str], Set[str]]:
    """
    Get the list of changed files in the git repository.
    
    Returns:
      - List of all changed file paths
      - Set of staged file paths
      - Set of renamed file paths (format: "old_path -> new_path")
      - Set of binary file paths
    """
    status_output = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    ).stdout.split("\n")
    
    if status_output == [""]:
        return [], set(), set(), set()
    
    all_changed = []
    staged = set()
    renamed = set()
    binary_files = set()
    
    for line in status_output:
        if not line:
            continue
        status, path_info = _extract_status_and_path_from_line(line)
        # Handle renamed files
        if status[0] == "R" or status[1] == "R":
            parts = path_info.split(" -> ")
            old_path, new_path = parts[0], parts[1]
            renamed.add(f"{old_path} -> {new_path}")
            all_changed.append(new_path)
            if status[0] in ["R", "M", "A"]:
                staged.add(new_path)
        else:
            file_path = path_info
            all_changed.append(file_path)
            if status[0] in ["M", "A", "D"]:
                staged.add(file_path)
    
    # Check for binary files on those paths
    for file_path in all_changed:
        if os.path.exists(file_path) and not os.path.isdir(file_path):
            try:
                with open(file_path, 'rb') as f:
                    content = f.read(1024)
                    if b'\x00' in content:
                        binary_files.add(file_path)
            except (IOError, UnicodeDecodeError):
                binary_files.add(file_path)
    
    return all_changed, staged, renamed, binary_files

def get_file_diff_data(file_path: str) -> Tuple[str, List[str], List[str]]:
    """
    Get diff data for a file.
    
    Returns:
        - Raw diff output (if available)
        - Old version lines (from HEAD)
        - New version lines (from working directory)
    """
    try:
        old_content = subprocess.run(
            ["git", "show", f"HEAD:{file_path}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        ).stdout
        old_lines = old_content.splitlines()
    except subprocess.CalledProcessError:
        old_lines = []
    
    new_lines = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                new_lines = f.read().splitlines()
        except Exception:
            new_lines = []
    
    try:
        diff = subprocess.run(
            ["git", "diff", "--staged", "--", file_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        ).stdout
        if not diff:
            diff = subprocess.run(
                ["git", "diff", "--", file_path],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            ).stdout
    except subprocess.CalledProcessError:
        diff = ""
    
    return diff, old_lines, new_lines

def create_interleaved_diff(file_path: str) -> str:
    """
    Create an interleaved diff showing additions, deletions,
    and unchanged lines.
    
    Returns a string with the interleaved diff.
    """
    raw_diff, old_lines, new_lines = get_file_diff_data(file_path)
    
    # For new files, show all lines as added.
    if not old_lines and new_lines:
        return "\n".join([f"+{line}" for line in new_lines])
    
    # For modified files, use difflib to produce a unified diff,
    # then later format it as an interleaved diff.
    diff_generator = difflib.unified_diff(
        old_lines,
        new_lines,
        n=0,
        lineterm=""
    )
    diff_lines = list(diff_generator)
    # Skip header lines (--- and +++)
    if len(diff_lines) > 2:
        diff_lines = diff_lines[2:]
    
    result = []
    old_line_num = 0
    new_line_num = 0
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith("@@"):
            parts = line.split(" ")
            if len(parts) >= 3:
                old_info = parts[1]
                new_info = parts[2]
                if "," in old_info:
                    old_start = int(old_info.split(",")[0][1:])
                else:
                    old_start = int(old_info[1:])
                if "," in new_info:
                    new_start = int(new_info.split(",")[0][1:])
                else:
                    new_start = int(new_info[1:])
                while old_line_num < old_start - 1 and new_line_num < new_start - 1:
                    result.append(f" {old_lines[old_line_num]}")
                    old_line_num += 1
                    new_line_num += 1
            i += 1
            continue
        
        if line.startswith("-"):
            result.append(line)
            old_line_num += 1
        elif line.startswith("+"):
            result.append(line)
            new_line_num += 1
        else:
            result.append(f" {line[1:]}")
            old_line_num += 1
            new_line_num += 1
        
        i += 1
    
    while new_line_num < len(new_lines):
        result.append(f" {new_lines[new_line_num]}")
        new_line_num += 1
    
    return "\n".join(result)

def get_file_content(file_path: str) -> Optional[str]:
    """Return file content if the file exists."""
    path = Path(file_path)
    if path.exists() and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            return None
    return None

def get_readme_content() -> Optional[str]:
    """Return content of README.md if it exists."""
    readme_paths = ["README.md", "Readme.md", "readme.md"]
    for path in readme_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                continue
    return None

def get_file_extension(file_path: str) -> str:
    """
    Return file extension for syntax highlighting.
    Maps some common extensions.
    """
    ext = os.path.splitext(file_path)[1].lstrip('.')
    ext_map = {
        "js": "javascript",
        "ts": "typescript",
        "jsx": "jsx",
        "tsx": "tsx",
        "md": "markdown",
        "py": "python",
        "rb": "ruby",
        "go": "go",
        "c": "c",
        "cpp": "cpp",
        "h": "cpp",
        "hpp": "cpp",
        "cs": "csharp",
        "java": "java",
        "php": "php",
        "sh": "bash",
        "yml": "yaml",
        "yaml": "yaml",
        "json": "json",
        "css": "css",
        "html": "html",
        "xml": "xml",
        "sql": "sql",
        "rs": "rust",
        "kt": "kotlin",
        "swift": "swift",
        "dart": "dart",
    }
    return ext_map.get(ext.lower(), ext) or "text"

def format_prompt(selected_files: List[str],
                    renamed_files: Set[str],
                    binary_files: Set[str]) -> str:
    """Format the prompt with the repository README, changed files,
    and file path changes."""
    explanation_snippet = """This prompt contains code changes from a Git repository for review.

**File Content Legend:**
*   Lines starting with `+` have been added.
*   Lines starting with `-` have been removed.
*   Lines starting with a space ` ` are unchanged context.

---
"""
    parts = [explanation_snippet] # Start the parts list with the snippet
    
    # Add README if it exists.
    readme_content = get_readme_content()
    if readme_content:
        do_readme = Confirm.ask("Include repository's README?", default=False)
    if do_readme:
        parts.append("# Repository's README:\n```\n")
        parts.append(readme_content)
        parts.append("\n```\n---\n")
    
    parts.append("# Changed Files:\n")
    deleted_files = []
    for file_path in selected_files:
        # Skip binary files for diff generation.
        if file_path in binary_files:
            continue
        # If the file no longer exists, mark it as deleted.
        if not os.path.exists(file_path):
            deleted_files.append(file_path)
            continue
        interleaved_diff = create_interleaved_diff(file_path)
        if not interleaved_diff:
            continue
        parts.append(f"## {file_path}\n")
        lang = get_file_extension(file_path)
        parts.append(f"```{lang}")
        parts.append(interleaved_diff)
        parts.append("```\n")
    
    if deleted_files:
        parts.append("---\n# Deleted Files:\n")
        for dfile in deleted_files:
            parts.append(f"* {dfile}\n")
    
    # Add renamed files if any of the new paths are selected.
    relevant_renames = []
    for rename_info in renamed_files:
        old_path, new_path = rename_info.split(" -> ")
        if new_path in selected_files:
            relevant_renames.append(rename_info)
    
    if relevant_renames:
        parts.append("---\n# File Path Changes (Renames):\n")
        for rename_info in relevant_renames:
            parts.append(f"* {rename_info}\n")
    
    # Mention selected binary files.
    selected_binaries = [f for f in selected_files if f in binary_files]
    if selected_binaries:
        parts.append("---\n# Binary Files (Content Skipped):\n")
        for bin_file in selected_binaries:
            parts.append(f"* {bin_file}\n")
    
    return "\n".join(parts)

def preview_prompt(prompt_text: str) -> None:
    """Display a preview of the prompt using less if available."""
    with tempfile.NamedTemporaryFile(
        mode="w+", delete=False, suffix=".md", encoding="utf-8"
    ) as temp:
        temp.write(prompt_text)
        temp_path = temp.name
    try:
        subprocess.run(["less", "-R", temp_path], check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        console.print(Markdown(prompt_text))
    try:
        os.unlink(temp_path)
    except Exception:
        pass

def main():
    console.print(
        Panel.fit(
            "[bold green]RepoDiff[/bold green] - Generate code review prompts from Git changes",
            box=box.ROUNDED,
            border_style="bright_blue",
        )
    )
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Checking git repository..."),
        transient=True,
    ) as progress:
        progress.add_task("check", total=None)
        if not is_git_repo():
            console.print("[bold red]Error:[/bold red] Not a git repository!")
            sys.exit(1)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Finding changed files..."),
        transient=True,
    ) as progress:
        progress.add_task("find", total=None)
        all_changed, staged_files, renamed_files, binary_files = get_changed_files()
    
    if not all_changed:
        console.print("[bold yellow]No changed files found![/bold yellow]")
        sys.exit(0)
    
    table = Table(title="Changed Files", box=box.ROUNDED)
    table.add_column("Status", style="cyan")
    table.add_column("Path", style="green")
    table.add_column("Type", style="yellow")
    
    for file_path in sorted(all_changed):
        status = "Staged" if file_path in staged_files else "Unstaged"
        file_type = "Binary" if file_path in binary_files else "Text"
        table.add_row(status, file_path, file_type)
    
    console.print(table)
    
    choices = [
        {
            "name": f"{path}",
            "checked": path in staged_files and path not in binary_files,
            "disabled": path in binary_files and "Binary file (read-only in selection)"
        }
        for path in all_changed
    ]
    
    selected_files = questionary.checkbox(
        "Select files to include in the prompt:",
        choices=choices,
        style=custom_style,
    ).ask()
    
    if not selected_files:
        console.print("[bold yellow]No files selected. Exiting.[/bold yellow]")
        sys.exit(0)
    
    prompt_text = format_prompt(selected_files, renamed_files, binary_files)
    
    console.print("[bold green]Prompt Generated![/bold green]")
    
    if Confirm.ask("Would you like to preview the prompt?", default=False):
        preview_prompt(prompt_text)
    
    if Confirm.ask("Copy to clipboard?", default=True):
        pyperclip.copy(prompt_text)
        console.print("[bold green]Copied to clipboard![/bold green]")
    
    console.print("[bold green]Done![/bold green]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Operation cancelled by user.[/bold yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        sys.exit(1)
