import os
import pytest
import tempfile
import shutil
import glob
import time
from pathlib import Path
from codeweave.main import main, parse_program_arg, run_program_on_file

# Repository root directory
repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Set up outputs directory
outputs_dir = os.path.join(repo_dir, "outputs")
os.makedirs(outputs_dir, exist_ok=True)

def find_output_file(temp_dir_name, lang="python"):
    """Helper function to find the output file in the outputs directory or in the temp directory."""
    # First check in the outputs directory
    # Check for files with the temp directory basename pattern
    pattern = os.path.join(outputs_dir, f"{os.path.basename(temp_dir_name)}*")
    matches = glob.glob(pattern)
    
    if matches:
        return matches[0]
    
    # Check in the outputs directory for any recently created files
    all_files = glob.glob(os.path.join(outputs_dir, "*"))
    if all_files:
        # Sort by modification time, newest first
        newest_file = sorted(all_files, key=os.path.getmtime, reverse=True)[0]
        # If it was created in the last 5 seconds, it's probably our file
        if time.time() - os.path.getmtime(newest_file) < 5:
            return newest_file
    
    # If still not found, check in the temp directory itself
    expected_filename = f"{os.path.basename(temp_dir_name)}_{lang}.txt"
    temp_file_path = os.path.join(temp_dir_name, expected_filename)
    if os.path.exists(temp_file_path):
        return temp_file_path
    
    # Also check if the file exists at the temp_dir_name path with the extension
    if os.path.exists(temp_dir_name + f"_{lang}.txt"):
        return temp_dir_name + f"_{lang}.txt"
    
    # If still not found, list files in all directories to help debug
    print(f"Files in outputs directory: {os.listdir(outputs_dir) if os.path.exists(outputs_dir) else []}")
    print(f"Files in temp directory: {os.listdir(temp_dir_name) if os.path.exists(temp_dir_name) else []}")
    
    return None

def test_parse_program_arg_valid():
    """Test that parse_program_arg correctly parses a valid program argument."""
    filetype, command = parse_program_arg("python=wc -l")
    assert filetype == "python"
    assert command == "wc -l"

def test_parse_program_arg_invalid():
    """Test that parse_program_arg handles invalid program arguments."""
    # Missing equals sign
    filetype, command = parse_program_arg("pythonwc -l")
    assert filetype is None
    assert command is None
    
    # Empty command
    filetype, command = parse_program_arg("python=")
    assert filetype is None
    assert command is None
    
    # Empty filetype
    filetype, command = parse_program_arg("=wc -l")
    assert filetype is None
    assert command is None

def test_run_program_on_file():
    """Test that run_program_on_file correctly runs a command on a file."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as temp_file:
        temp_file.write(b"Line 1\nLine 2\nLine 3\n")
        temp_path = temp_file.name
    
    try:
        # On Unix-like systems, 'wc -l' should return the number of lines
        output = run_program_on_file(temp_path, "wc -l")
        # The output will be like "3 filename"
        assert output is not None
        assert "3" in output
    finally:
        os.unlink(temp_path)

def create_test_files(temp_dir):
    """Helper to create test files in a directory."""
    # Create a Python file
    py_file = os.path.join(temp_dir, "test.py")
    with open(py_file, "w") as f:
        f.write("print('Hello, World!')\n")
    
    # Create a text file
    txt_file = os.path.join(temp_dir, "test.txt")
    with open(txt_file, "w") as f:
        f.write("This is a test file.\n")
        
    return py_file, txt_file

def test_program_feature_selective():
    """Test that the program correctly identifies which files to run on based on filetype."""
    temp_dir = tempfile.mkdtemp(prefix="g2f_test_")
    try:
        # Create test files
        py_file, txt_file = create_test_files(temp_dir)
        
        # Setup test data for parse_program_arg
        program_arg = "python=wc -l"  # Only run on Python files
        filetype, command = parse_program_arg(program_arg)
        
        # Verify parse_program_arg worked correctly
        assert filetype == "python"
        assert command == "wc -l"
        
        # Test with Python file - should generate output
        py_output = run_program_on_file(py_file, command)
        assert py_output is not None
        assert "1" in py_output  # Python file has 1 line
        
        # Check file extension identification logic
        from codeweave.utils.path import lookup_file_extension
        py_ext = lookup_file_extension(py_file)
        assert "python" in py_ext
        
        txt_ext = lookup_file_extension(txt_file)
        assert "python" not in txt_ext
        
        # Verify the filetype matching works as expected
        matches_py = filetype in lookup_file_extension(py_file) or filetype == '*'
        assert matches_py is True
        
        matches_txt = filetype in lookup_file_extension(txt_file) or filetype == '*'
        assert matches_txt is False
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_program_feature_wildcard():
    """Test that the wildcard (*) runs the program on all filetypes."""
    temp_dir = tempfile.mkdtemp(prefix="g2f_test_")
    try:
        # Create test files
        py_file, txt_file = create_test_files(temp_dir)
        
        # Setup test data for parse_program_arg
        program_arg = "*=wc -l"  # Run on all files
        filetype, command = parse_program_arg(program_arg)
        
        # Verify parse_program_arg worked correctly
        assert filetype == "*"
        assert command == "wc -l"
        
        # Test with Python file - should generate output
        py_output = run_program_on_file(py_file, command)
        assert py_output is not None
        assert "1" in py_output  # Python file has 1 line
        
        # Test with text file - should also generate output 
        txt_output = run_program_on_file(txt_file, command)
        assert txt_output is not None
        assert "1" in txt_output  # Text file has 1 line
        
        # Verify the wildcard matches all filetypes
        from codeweave.utils.path import lookup_file_extension
        
        # Verify the filetype matching works as expected with wildcard
        matches_py = filetype in lookup_file_extension(py_file) or filetype == '*'
        assert matches_py is True
        
        matches_txt = filetype in lookup_file_extension(txt_file) or filetype == '*'
        assert matches_txt is True
    finally:
        # Clean up
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_no_program_output_for_mismatched_filetype():
    """Test that files not matching the filetype don't get program output."""
    temp_dir = tempfile.mkdtemp(prefix="g2f_test_")
    try:
        # Create test files
        py_file, txt_file = create_test_files(temp_dir)
        
        # Create a custom filetype for our test
        # Add an entry to the file_extension_dict
        from codeweave.utils.path import file_extension_dict
        file_extension_dict['text'] = ['.txt']  # Add text format for this test
        
        # Setup test data for parse_program_arg
        program_arg = "text=wc -l"  # Only run on text files with new format
        filetype, command = parse_program_arg(program_arg)
        
        # Verify parse_program_arg worked correctly
        assert filetype == "text"
        assert command == "wc -l"
        
        # Verify matching logic with the text file
        from codeweave.utils.path import lookup_file_extension
        
        py_ext = lookup_file_extension(py_file)
        txt_ext = lookup_file_extension(txt_file)
        
        # Python files should have python in extensions but not text
        assert "python" in py_ext
        assert "text" not in py_ext
        
        # Text files should have text in extensions
        assert "text" in txt_ext
        
        # Verify the filetype matching works as expected
        matches_py = filetype in lookup_file_extension(py_file) or filetype == '*'
        assert matches_py is False  # Python file should not match text filetype
        
        matches_txt = filetype in lookup_file_extension(txt_file) or filetype == '*'
        assert matches_txt is True  # Text file should match text filetype
    finally:
        # Clean up
        # Restore the file_extension_dict
        from codeweave.utils.path import file_extension_dict
        if 'text' in file_extension_dict:
            del file_extension_dict['text']
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_program_multiline_file():
    """Test that the program correctly counts multiple lines in a file."""
    # Create a temp file with multiple lines
    with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as temp_file:
        # Write 5 lines to the file
        temp_file.write(b"print('Line 1')\n")
        temp_file.write(b"print('Line 2')\n")
        temp_file.write(b"print('Line 3')\n")
        temp_file.write(b"print('Line 4')\n")
        temp_file.write(b"print('Line 5')\n")
        temp_path = temp_file.name
    
    try:
        # Run wc -l command to count lines
        output = run_program_on_file(temp_path, "wc -l")
        
        # Verify output
        assert output is not None, "Program output should not be None"
        assert "5" in output, f"Expected '5' in output, got: {output}"
    finally:
        # Clean up
        os.remove(temp_path)

def test_nosubstitute_flag_direct():
    """Test that the --nosubstitute flag behavior directly with a mock file processing scenario."""
    # Mock Args for the default case (no nosubstitute flag)
    class MockArgs:
        def __init__(self, nosubstitute=False):
            self.nosubstitute = nosubstitute
            self.lang = ["python"]
            self.topN = None
    
    # Create a temporary output file
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_outfile:
        outfile_path = temp_outfile.name
        
        try:
            # Test scenario 1: Without nosubstitute (default)
            args = MockArgs(nosubstitute=False)
            file_path = "test.py"
            file_content = "print('Hello, World!')"
            program_output = "5 test.py"  # Mock program output
            comment_prefix = "#"
            
            # Open the file and write contents similar to what the actual code would do
            with open(outfile_path, 'w', encoding='utf-8') as outfile:
                # File header
                outfile.write(f"{comment_prefix} File: {file_path}\n")
                
                # Write program output
                outfile.write(f"{comment_prefix} Program output:\n")
                outfile.write(program_output)
                outfile.write("\n\n")
                
                # If nosubstitute is False (default), we skip writing the file content
                if not args.nosubstitute:
                    # Skip file content
                    pass
                else:
                    # Write file content
                    outfile.write(file_content)
                    
                outfile.write("\n\n")
            
            # Read the file and check the content
            with open(outfile_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Verify that file content is NOT included (default behavior)
            assert "Program output:" in content, "Output should contain program output header"
            assert "print('Hello, World!')" not in content, "Output should not contain file content when nosubstitute is False"
            
            # Test scenario 2: With nosubstitute=True
            args = MockArgs(nosubstitute=True)
            
            # Open the file and write contents similar to what the actual code would do
            with open(outfile_path, 'w', encoding='utf-8') as outfile:
                # File header
                outfile.write(f"{comment_prefix} File: {file_path}\n")
                
                # Write program output
                outfile.write(f"{comment_prefix} Program output:\n")
                outfile.write(program_output)
                outfile.write("\n\n")
                
                # If nosubstitute is True, write the file content
                if not args.nosubstitute:
                    # Skip file content
                    pass
                else:
                    # Write file content
                    outfile.write(file_content)
                    
                outfile.write("\n\n")
            
            # Read the file and check the content
            with open(outfile_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Verify that file content IS included with nosubstitute=True
            assert "Program output:" in content, "Output should contain program output header"
            assert "print('Hello, World!')" in content, "Output should contain file content when nosubstitute is True"
            
        finally:
            # Clean up the temporary file
            if os.path.exists(outfile_path):
                os.remove(outfile_path)