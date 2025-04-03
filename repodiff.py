#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path
import tempfile
import pyperclip
import difflib
from typing import List, Dict, Tuple, Set, Optional

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

def _extract_status_and_path_from_line(line: str) -> tuple[str, str]:
    """
    Extract the status code and file path from a git status --porcelain line.

    The porcelain output is expected to be two characters for the status followed
    by a space and then the file path. For example:
        'M pipelines/pipeline_context.py'
        ' M services/implementation/azure_openai_chat_completion_service.py'
        '?? TODO.md'
        
    This function returns a tuple (status, file_path).
    """
    # The first two characters represent the git status
    status = line[:2]
    # The rest of the line (starting at position 2) is the path; strip any whitespace
    file_path = line[2:].lstrip()
    return status, file_path



def get_changed_files() -> Tuple[List[str], Set[str], Set[str], Set[str]]:
    """
    Get the list of changed files in the git repository.
    
    Returns:
        Tuple containing:
        - List of all changed file paths
        - Set of staged file paths
        - Set of renamed file paths (format: "old_path -> new_path")
        - Set of binary file paths
    """
    # Get status output
    status_output = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    ).stdout.strip().split("\n")
    
    # Filter out empty lines
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
            # Example: R  old_name -> new_name
            parts = path_info.split(" -> ")
            old_path, new_path = parts[0], parts[1]
            renamed.add(f"{old_path} -> {new_path}")
            
            # For renames, add the new path to the list
            all_changed.append(new_path)
            if status[0] in ["R", "M", "A"]:
                staged.add(new_path)
        else:
            file_path = path_info
            all_changed.append(file_path)
            
            # Check if file is staged
            if status[0] in ["M", "A", "D"]:
                staged.add(file_path)
    
    # Check for binary files
    for file_path in all_changed:
        if os.path.exists(file_path) and not os.path.isdir(file_path):
            try:
                with open(file_path, 'rb') as f:
                    content = f.read(1024)
                    # Simple binary check: if there's a null byte, it's likely binary
                    if b'\x00' in content:
                        binary_files.add(file_path)
            except (IOError, UnicodeDecodeError):
                # If we can't read it or decode it, consider it binary
                binary_files.add(file_path)
    
    return all_changed, staged, renamed, binary_files

def get_file_diff_data(file_path: str) -> Tuple[str, List[str], List[str]]:
    """
    Get diff data for a file.
    
    Returns:
        Tuple containing:
        - The raw diff output
        - List of the old file lines
        - List of the new file lines
    """
    # Try to get the old version of the file
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
        # File is new and doesn't exist in HEAD
        old_lines = []
    
    # Get the current version
    new_lines = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                new_lines = f.read().splitlines()
        except Exception:
            new_lines = []
    
    # Get the raw diff
    try:
        # Try for staged diff first
        diff = subprocess.run(
            ["git", "diff", "--staged", "--", file_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        ).stdout
        
        # If no staged diff, try unstaged
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
    Create an interleaved diff showing additions, deletions, and unchanged lines.
    Returns a string with the interleaved diff.
    """
    raw_diff, old_lines, new_lines = get_file_diff_data(file_path)
    
    # If file is new, just return all lines as added
    if not old_lines and new_lines:
        return "\n".join([f"+{line}" for line in new_lines])
    
    # If file is deleted, just return all lines as removed
    if old_lines and not new_lines:
        return "\n".join([f"-{line}" for line in old_lines])
    
    # For modified files, use difflib to get the diff
    diff_generator = difflib.unified_diff(
        old_lines, 
        new_lines,
        n=0,  # No context lines - we'll handle this ourselves
        lineterm=""
    )
    
    # Skip the first two lines (the --- and +++ header)
    diff_lines = list(diff_generator)
    if len(diff_lines) > 2:
        diff_lines = diff_lines[2:]
    
    # Parse the diff and create the interleaved view
    result = []
    old_line_num = 0
    new_line_num = 0
    
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        
        # Parse the @@ line to get line numbers
        if line.startswith("@@"):
            parts = line.split(" ")
            if len(parts) >= 3:
                old_info = parts[1]
                new_info = parts[2]
                
                # Parse the line number info
                if "," in old_info:
                    old_start = int(old_info.split(",")[0][1:])
                    old_count = int(old_info.split(",")[1])
                else:
                    old_start = int(old_info[1:])
                    old_count = 1
                
                if "," in new_info:
                    new_start = int(new_info.split(",")[0][1:])
                    new_count = int(new_info.split(",")[1])
                else:
                    new_start = int(new_info[1:])
                    new_count = 1
                
                # Add unchanged lines up to this point
                while old_line_num < old_start - 1 and new_line_num < new_start - 1:
                    result.append(f" {old_lines[old_line_num]}")
                    old_line_num += 1
                    new_line_num += 1
                
                old_line_num = old_start - 1
                new_line_num = new_start - 1
            i += 1
            continue
        
        # Handle removed, added, or context lines
        if line.startswith("-"):
            result.append(line)
            old_line_num += 1
        elif line.startswith("+"):
            result.append(line)
            new_line_num += 1
        else:
            # This is an unchanged line
            result.append(f" {line[1:]}")
            old_line_num += 1
            new_line_num += 1
        
        i += 1
    
    # Add any remaining unchanged lines
    while new_line_num < len(new_lines):
        result.append(f" {new_lines[new_line_num]}")
        new_line_num += 1
    
    return "\n".join(result)

def get_file_content(file_path: str) -> Optional[str]:
    """Get the content of a file if it exists."""
    path = Path(file_path)
    if path.exists() and path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            return None  # Binary file or encoding issues
    return None  # File doesn't exist

def get_readme_content() -> Optional[str]:
    """Get the content of README.md if it exists."""
    readme_paths = ["README.md", "Readme.md", "readme.md"]
    for path in readme_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return None

def get_file_extension(file_path: str) -> str:
    """Get the file extension for syntax highlighting."""
    ext = os.path.splitext(file_path)[1].lstrip('.')
    
    # Map some common extensions to their language
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

def format_prompt(selected_files: List[str], renamed_files: Set[str], 
                  binary_files: Set[str]) -> str:
    """Format the selected files into a prompt."""
    parts = []
    
    # Add README if exists
    readme_content = get_readme_content()
    if readme_content:
        parts.append("# Repository README\n")
        parts.append(readme_content)
        parts.append("\n---\n")
    
    # Add selected files
    parts.append("# Changed Files\n")
    
    for file_path in selected_files:
        # Skip binary files
        if file_path in binary_files:
            continue
        
        # Get the interleaved diff (content + diff markers)
        interleaved_diff = create_interleaved_diff(file_path)
        if not interleaved_diff:
            continue
        
        parts.append(f"## {file_path}\n")
        
        # Detect file extension for syntax highlighting hint
        lang = get_file_extension(file_path)
        
        # Add the interleaved diff with syntax highlighting
        parts.append(f"```{lang}")
        parts.append(interleaved_diff)
        parts.append("```\n")
    
    # Add renamed files if any selected are in the rename list
    relevant_renames = []
    for rename_info in renamed_files:
        old_path, new_path = rename_info.split(" -> ")
        if new_path in selected_files:
            relevant_renames.append(rename_info)
    
    if relevant_renames:
        parts.append("# File Path Changes\n")
        for rename_info in relevant_renames:
            parts.append(f"* {rename_info}\n")
    
    # Add binary files notice if any were selected but skipped
    selected_binaries = [f for f in selected_files if f in binary_files]
    if selected_binaries:
        parts.append("# Binary Files (Skipped)\n")
        for bin_file in selected_binaries:
            parts.append(f"* {bin_file}\n")
    
    return "\n".join(parts)

def preview_prompt(prompt_text: str) -> None:
    """Show a preview of the generated prompt."""
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.md', encoding='utf-8') as temp:
        temp.write(prompt_text)
        temp_path = temp.name
    
    # Use less to preview if available, otherwise just print
    try:
        subprocess.run(['less', '-R', temp_path], check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        console.print(Markdown(prompt_text))
    
    # Clean up temp file
    try:
        os.unlink(temp_path)
    except Exception:
        pass

def main():
    console.print(Panel.fit(
        "[bold green]GitPrompt[/bold green] - Generate code review prompts from Git changes",
        box=box.ROUNDED,
        border_style="bright_blue"
    ))
    
    # Check if current directory is a git repository
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Checking git repository..."),
        transient=True,
    ) as progress:
        progress.add_task("check", total=None)
        if not is_git_repo():
            console.print("[bold red]Error:[/bold red] Not a git repository!")
            sys.exit(1)
    
    # Get changed files
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
    
    # Display changed files
    table = Table(title="Changed Files", box=box.ROUNDED)
    table.add_column("Status", style="cyan")
    table.add_column("Path", style="green")
    table.add_column("Type", style="yellow")
    
    for file_path in sorted(all_changed):
        status = "Staged" if file_path in staged_files else "Unstaged"
        file_type = "Binary" if file_path in binary_files else "Text"
        table.add_row(status, file_path, file_type)
    
    console.print(table)
    
    # Prepare choices for questionary - this should fix the cutting off issue
    choices = [
        {
            "name": f"{path}",  # Ensure it's a string with proper formatting
            "checked": path in staged_files and path not in binary_files,
            "disabled": path in binary_files and "Binary file (included in list only)"
        }
        for path in all_changed
    ]
    
    # Let user select files
    selected_files = questionary.checkbox(
        "Select files to include in the prompt:",
        choices=choices,
        style=custom_style
    ).ask()
    
    if not selected_files:
        console.print("[bold yellow]No files selected. Exiting.[/bold yellow]")
        sys.exit(0)
    
    # Generate the prompt
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Generating prompt..."),
        transient=True,
    ) as progress:
        progress.add_task("generate", total=None)
        prompt_text = format_prompt(selected_files, renamed_files, binary_files)
    
    # Display a preview
    console.print("[bold green]Prompt Generated![/bold green]")
    
    # Changed default to No for preview
    if Confirm.ask("Would you like to preview the prompt?", default=False):
        preview_prompt(prompt_text)
    
    # Changed default to Yes for copying to clipboard
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
