#!/usr/bin/env python3
"""
Replying on Git-CLI to do git ops, mainly
- Extract author info
- Root folder detection
"""

import os
import subprocess
from typing import List, Dict, Optional, Any
import re

from .logs import setup_logging

logger = setup_logging()

def get_git_repo_url(directory: str) -> Optional[str]:
    """Get the remote repository URL for a Git repository
    
    Args:
        directory: Path to a directory within a Git repository
        
    Returns:
        URL of the repository's origin remote, or None if not in a Git repository
    """
    try:
        cwd = os.getcwd()
        os.chdir(directory)
        cmd = ["git", "remote", "get-url", "origin"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        remote_url = result.stdout.strip()
        os.chdir(cwd)
        return remote_url
    except subprocess.CalledProcessError as e:
        logger.debug(f"Error getting Git repository URL: {e}")
        try:
            cwd = os.getcwd()
            os.chdir(directory)
            cmd = ["git", "rev-parse", "--is-inside-work-tree"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            os.chdir(cwd)
            if result.stdout.strip() == "true":
                return None
        except Exception:
            pass
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return None
    except Exception as e:
        logger.debug(f"Error getting Git repository URL: {e}")
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return None

def get_git_reference(directory: str) -> Optional[str]:
    """Get the current Git reference (branch name, tag, or commit hash)
    
    Args:
        directory: Path to a directory within a Git repository
        
    Returns:
        Current Git reference, or None if not in a Git repository
    """
    try:
        cwd = os.getcwd()
        os.chdir(directory)
        cmd = ["git", "symbolic-ref", "--short", "HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            branch_name = result.stdout.strip()
            os.chdir(cwd)
            return branch_name
        cmd = ["git", "describe", "--tags", "--exact-match"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            tag_name = result.stdout.strip()
            os.chdir(cwd)
            return tag_name
        cmd = ["git", "rev-parse", "--short", "HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            commit_hash = result.stdout.strip()
            os.chdir(cwd)
            return commit_hash
        
        # Return to the original directory
        os.chdir(cwd)
        
        return None
    except Exception as e:
        logger.debug(f"Error getting Git reference: {e}")
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return None

def get_file_authors_by_line_range(file_path: str, start_line: int, end_line: int) -> List[Dict[str, Any]]:
    """Get authors and blame information for a range of lines in a file
    
    Args:
        file_path: Path to the file
        start_line: First line number (1-based)
        end_line: Last line number (1-based)
        
    Returns:
        List of dictionaries with author information for each line in the range
    """
    if not start_line or not end_line or start_line > end_line:
        return []
    blame_start = start_line - 1
    blame_end = end_line
    
    try:
        directory = os.path.dirname(file_path)
        if not directory:
            directory = "."
        filename = os.path.basename(file_path)
        cwd = os.getcwd()
        os.chdir(directory)
        cmd = ["git", "blame", "-p", f"-L{blame_start},{blame_end}", "--", filename]
        result = subprocess.run(cmd, capture_output=True, text=True)
        os.chdir(cwd)
        if result.returncode != 0:
            logger.debug(f"Error running git blame: {result.stderr}")
            return []
        blame_output = result.stdout
        authors = parse_git_blame_output(blame_output, blame_start)
        
        return authors
    except Exception as e:
        logger.debug(f"Error getting file authors: {e}")
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return []

def parse_git_blame_output(blame_output: str, start_line_offset: int) -> List[Dict[str, Any]]:
    """Parse the output of git blame -p to extract author information
    
    Args:
        blame_output: Output of git blame -p command
        start_line_offset: Line number offset to calculate actual line numbers
        
    Returns:
        List of dictionaries with author information for each line
    """
    lines = blame_output.split('\n')
    authors = []
    current_commit = None
    current_author = None
    current_author_mail = None
    current_author_time = None
    current_line = None
    
    for line in lines:
        header_match = re.match(r'^([0-9a-f]{40}) (\d+) (\d+)( \d+)?', line)
        if header_match:
            current_commit = header_match.group(1)
            current_line = int(header_match.group(3)) + start_line_offset
            continue
        if line.startswith('author '):
            current_author = line[7:]
        elif line.startswith('author-mail '):
            current_author_mail = line[12:].strip('<>')
        elif line.startswith('author-time '):
            current_author_time = line[12:]
        if current_commit and current_author and current_author_mail and current_author_time and current_line is not None:
            authors.append({
                'line': current_line,
                'commit': current_commit,
                'author': current_author,
                'email': current_author_mail,
                'time': current_author_time
            })
            current_commit = None
            current_author = None
            current_author_mail = None
            current_author_time = None
            current_line = None
            
    return authors

def is_git_repository(directory: str) -> bool:
    """Check if a directory is within a Git repository
    
    Args:
        directory: Path to check
        
    Returns:
        True if the directory is within a Git repository, False otherwise
    """
    try:
        cwd = os.getcwd()
        os.chdir(directory)
        cmd = ["git", "rev-parse", "--is-inside-work-tree"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        os.chdir(cwd)
        
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return False

def get_git_root(directory: str) -> Optional[str]:
    """Get the root directory of a Git repository
    
    Args:
        directory: Path to a directory within a Git repository
        
    Returns:
        Absolute path to the Git repository root, or None if not in a Git repository
    """
    try:
        cwd = os.getcwd()
        os.chdir(directory)
        cmd = ["git", "rev-parse", "--show-toplevel"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        root_path = result.stdout.strip()
        os.chdir(cwd)
        return root_path
    except subprocess.CalledProcessError as e:
        logger.debug(f"Error getting Git repository root: {e}")
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return None
    except Exception as e:
        logger.debug(f"Error getting Git repository root: {e}")
        try:
            os.chdir(cwd)
        except Exception:
            pass
        return None
        
def get_relative_path_from_git_root(file_path: str) -> Optional[str]:
    """Get the path of a file relative to the Git repository root
    
    Args:
        file_path: Absolute path to a file within a Git repository
        
    Returns:
        Path of the file relative to the Git repository root, or None if not in a Git repository
    """
    logger.debug(f"Getting relative path from git root for: {file_path}")
    if not file_path:
        return None
    if file_path.startswith("http://") or file_path.startswith("https://"):
        logger.debug(f"Skipping URL: {file_path}")
        return None
    fragment = ""
    if "#" in file_path:
        file_path, fragment = file_path.split("#", 1)
        fragment = f"#{fragment}"
    directory = os.path.dirname(file_path)
    if not os.path.isdir(directory):
        logger.debug(f"Directory does not exist: {directory}")
        return None
    root_path = get_git_root(directory)
    if not root_path:
        logger.debug(f"Not in a Git repository: {directory}")
        return None
    try:
        rel_path = os.path.relpath(file_path, root_path)
        logger.debug(f"Relative path: {rel_path} (from {file_path} relative to {root_path})")
        if rel_path.startswith(".."):
            logger.debug(f"Path is outside repository: {rel_path}")
            return None
        return rel_path + fragment
    except Exception as e:
        logger.debug(f"Error getting relative path: {e}")
        return None
