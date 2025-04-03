# RepoDiff

**RepoDiff** is a Python CLI tool that generates clean, formatted prompts from Git changes, perfect for code reviews or LLM input. It interactively selects changed files, shows interleaved diffs (`+`/`-`), and includes READMEs—ready for clipboard or direct sharing.  

*Perfect for AI pair-programming!* 🚀

<img width="614" alt="image" src="https://github.com/user-attachments/assets/af205cfc-6318-4fa2-ab9e-b0fd1190a24e" />

It interactively lists changed files, allows selection, and generates a formatted output including an interleaved diff view, the repository README, and path change information, ready to be copied to the clipboard.

## Features

*   Detects the current Git repository.
*   Lists staged and unstaged file changes.
*   Provides an interactive checklist to select files (staged text files are pre-selected).
*   Generates an *interleaved diff* format (showing `+`/`-`/` ` lines) for selected files.
*   Includes repository `README.md` content at the top (if found).
*   Separately lists renamed, deleted, and skipped binary files among the selection.
*   Optionally previews the generated prompt.
*   Copies the final formatted prompt to the clipboard (default).
*   Uses a clean, colorful CLI interface.

## Requirements

*   Python 3.7+
*   `git` command line tool installed and available in PATH.
*   `pip` for installing Python packages.

## Installation

1.  **Download:** Save the script code as `repodiff.py`.

2.  **Install Dependencies:**
    ```bash
    pip install rich questionary pyperclip
    ```

3.  **Make Executable:**
    ```bash
    chmod +x repodiff.py
    ```

4.  **Move to PATH:** (Optional, but recommended for global access)
    ```bash
    # Create a local bin directory if you don't have one
    mkdir -p ~/bin
    # Move the script (renaming it to 'repodiff')
    mv repodiff.py ~/bin/repodiff
    # Ensure ~/bin is in your system's PATH
    # (You might need to add 'export PATH="$HOME/bin:$PATH"' to your ~/.bashrc or ~/.zshrc)
    ```

## Usage

1.  Navigate to the root directory of your Git repository containing changes.
2.  Run the command:
    ```bash
    repodiff
    ```
3.  Follow the on-screen prompts to select files.
4.  Confirm if you want to preview and/or copy the result to your clipboard.

## Output Format

The generated prompt includes:

1.  An explanation of the format.
2.  The content of `README.md` (if found).
3.  For each selected text file:
    *   The file path as a header.
    *   A code block containing the file content with changes marked inline:
        *   `+`: Added line
        *   `-`: Removed line
        *   ` `: Unchanged line
4.  Separate sections listing selected files that were deleted, renamed, or skipped (binary).
