#!/usr/bin/env python3
import re, sys, io, os, json
import argparse
import frontmatter
from .logs import setup_logging

logger = setup_logging()

def build_link(libname, filename, line, repo_url, branch):
    """Build a link to a source file in the repository
    
    Args:
        libname: Library name
        filename: Source file name
        line: Line number
        repo_url: URL of the code repository
        branch: Branch name
        
    Returns:
        Markdown link to the source location
    """
    return f"[{filename}#{line}]({repo_url}/blob/{branch}/tests/{libname}/{filename}#L{line})"

def parse_path(path, libname, name, content, repo_url, branch):
    """Parse a test path and extract assertion information
    
    Args:
        path: Test path containing sections and assertions
        libname: Library name
        name: Current test name/section
        content: Current content to append to
        repo_url: URL of the code repository
        branch: Branch name
        
    Returns:
        Updated content with assertion information
    """
    newcontent = content
    for e in path:
        if e["kind"] == "section":
            name = f"{name}\n{e['name']}"
            newcontent = parse_path(e["path"], libname, name, newcontent, repo_url, branch)
        if e["kind"] == "assertion":
            status = f"<i class='fa-sharp fa-solid fa-check -text-primary'></i>" if e["status"] else f"<i class='fa-sharp fa-solid fa-circle-exclamation -text-warning'></i>"
            newcontent = newcontent + ((
                f"\n---\n\n"
                f"{status} "
                f"From file {build_link(libname, e['source-location']['filename'], e['source-location']['line'], repo_url, branch)}."
                f"\nBelonging to the test section scoped as:\n"
                f"\n```"
                f"{name}"
                f"\n```\n\n"
            ))
    return newcontent

def parse_serial_tests(data, reports_dir, repo_url, branch):
    """Parse serial test report data
    
    Args:
        data: JSON data from test report
        reports_dir: Directory containing test reports
        repo_url: URL of the code repository
        branch: Branch name
        
    Returns:
        Tuple of (content, tags, libname, basename)
    """
    tags = set()
    content = ""
    basename = re.sub('Tests$', '', os.path.basename(f"{reports_dir}"))
    meta = data['metadata']
    mpi = "Serial" if "serial" in meta["filters"] else "Parallel"
    libname = meta["name"]
    case = re.sub("\[#[\w-]*\]", "", meta["filters"].replace("[serial]", "")).strip()
    test = data['test-run']
    stats = data["test-run"]["totals"]
    nTests = stats["test-cases"]["passed"]+stats["test-cases"]["failed"]
    if nTests == 0:
        return "", set(), "", ""
    content = content + ((
        f"\n## {mpi} unit tests for `{basename}` in `{libname}` library on `{case}` case\n\n"
        f"Tests were performed using [Catch2](https://github.com/catchorg/Catch2) version "
        f'`{meta["catch2-version"]}` (rng-seed: `{meta["rng-seed"]}`) with the following filters: `{meta["filters"]}`.\n\n'
        f'<i class="fa-sharp fa-solid fa-check -text-primary"></i> '
        f'<span class="-text-primary">{stats["test-cases"]["passed"]+stats["test-cases"]["fail-but-ok"]} Passing</span> test cases '
        f' (<span class="-text-primary">{stats["assertions"]["passed"]+stats["test-cases"]["fail-but-ok"]}</span> expressions), '
        f'<i class="fa-sharp fa-solid fa-circle-exclamation -text-warning"></i> '
        f'<span class="-text-warning">{stats["test-cases"]["failed"]-stats["test-cases"]["fail-but-ok"]} Failing</span> test cases '
        f' (<span class="-text-warning">{stats["assertions"]["failed"]-stats["test-cases"]["fail-but-ok"]}</span> expressions).\n\n'
    ))
    for testcase in test["test-cases"]:
        info = testcase['test-info']
        stats = testcase['totals']
        runs = testcase['runs']
        tags |= set(info['tags'])
        link = build_link(libname, info["source-location"]["filename"], info["source-location"]["line"], repo_url, branch)
        content = content + ((
            f'### {info["name"]}\n\n'
            f'Defined in {link}\n\n'
            f'With expressions:\n\n'
        ))
        for expr in runs:
            name = ""
            new_content = parse_path(expr["path"], libname, name, content, repo_url, branch)
            content = new_content
    return content, tags, libname, basename

def process_test_reports(reports_dir, output_file, repo_url, branch):
    """Process test reports and generate markdown output
    
    Args:
        reports_dir: Directory containing test reports
        output_file: Output markdown file path
        repo_url: URL of the code repository
        branch: Branch name
        
    Returns:
        0 on success, non-zero on error
    """
    logger.info(f"Processing test reports from {reports_dir}")
    post = frontmatter.Post(content = ((
        '{{< alert title="Note:" >}}\n'
        'The unit tests pages are automatically generated from the test reports. Some important points to mention:\n'
        '- The random number generator is seeded with the same seed for parallel/serial runs for the same test case.\n'
        '- Number of passing tests is the "effective" one (including the ones that fail but are expected to fail)".\n'
        '- Number of failing tests is the "effective" one (only the ones that fail and are not expected to fail)".\n'
        '{{< /alert >}}\n'
    )))
    post_tags = set()
    lib = ""
    testname = ""
    
    report_count = 0
    for filename in os.listdir(reports_dir):
        if filename.endswith('_serial.json'):
            filepath = os.path.join(reports_dir, filename)
            logger.debug(f"Processing report: {filepath}")
            try:
                with open(filepath) as f:
                    data = json.load(f)
                content, ttags, tlib, ttestname = parse_serial_tests(data, reports_dir, repo_url, branch)
                lib = tlib if tlib != "" else lib
                testname = ttestname if ttestname != "" else testname
                post.content = post.content + content
                post_tags |= ttags
                report_count += 1
            except Exception as e:
                logger.error(f"Error processing report {filepath}: {e}")
                return 1
    
    if lib == "" and testname == "":
        logger.warning("No valid test reports found")
        return 0
        
    post.metadata = {
        'title': f"Unit tests for {lib} - {testname}",
        'layout': 'unittest',
        'tags': list(post_tags),
    }
    
    try:
        logger.info(f"Writing output to {output_file}")
        b = io.BytesIO()
        frontmatter.dump(post, b)
        with open(output_file, "wb") as f:
            f.write(b.getbuffer())
        logger.info(f"Successfully processed {report_count} test reports")
        return 0
    except Exception as e:
        logger.error(f"Error writing output file: {e}")
        return 1

def main():
    """Main entry point for the unittesting report processor"""
    parser = argparse.ArgumentParser(
        description="""Process unit test reports and generate markdown documentation.
        This is very specific to OpenFOAM code unit-tested with foamUT""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "reports_dir",
        help="Directory containing test report JSON files"
    )
    parser.add_argument(
        "output_file",
        help="Output markdown file path"
    )
    parser.add_argument(
        "repo_url",
        help="URL of the code repository"
    )
    parser.add_argument(
        "branch",
        help="Branch name for source links"
    )
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.reports_dir):
        logger.error(f"Reports directory does not exist: {args.reports_dir}")
        return 1
    output_dir = os.path.dirname(args.output_file)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
            logger.debug(f"Created output directory: {output_dir}")
        except Exception as e:
            logger.error(f"Error creating output directory: {e}")
            return 1
    return process_test_reports(args.reports_dir, args.output_file, args.repo_url, args.branch)

if __name__ == "__main__":
    sys.exit(main() or 0)
