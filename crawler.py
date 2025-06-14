import os
import requests
from bs4 import BeautifulSoup
from readability import Document
from urllib.parse import urljoin, urlparse
from tqdm import tqdm
import re
import time
import argparse
import textwrap
import fnmatch # Import fnmatch for wildcard matching
import logging

'''
Copyright [2025] [piebru at gmail]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

__version__ = "0.2.0"

# Default Configuration
BASE_URL = "https://llmstxt.org/"  # Root URL of documentation
URL_PATTERN_DEFAULT_STRING = r'^https?://llmstxt\.org/' # Default as string for argparse
OUTPUT_FILE_DEFAULT = "llms.txt"
OUTPUT_FILE_FULL_DEFAULT = "llms-full.txt" # For full content embedding
OUTPUT_DIRECTORY_DEFAULT_BASE = "./output" # Base for default output directory
LOG_FILE_DEFAULT = "crawler.log"
USER_AGENT_DEFAULT = "DocsCrawler/1.0 (+https://llmstxt.org/crawler)"
#USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.52 Safari/537.36"
LLMS_TXT_SITE_TITLE = "LLMs.txt Project" # Customize this: H1 Title for llms.txt
LLMS_TXT_SITE_SUMMARY_DEFAULT = "Guidance for LLMs on how to best use this site's content." # Customize this: Blockquote summary
LLMS_TXT_DETAILS_PLACEHOLDER = (
    "You can add more detailed information about the project or how to interpret the files here. "
    "This section can contain paragraphs, lists, etc., but no H2 or lower headings."
)
REQUEST_DELAY_DEFAULT = 1  # Seconds between requests (avoid overloading servers)
MAX_PAGES_DEFAULT = 1000 # Maximum number of pages to crawl
MAX_URL_LENGTH = 2000 # Define a reasonable max URL length
SKIP_ADJACENT_REPETITIVE_PATHS_DEFAULT = False # Default for new feature
REQUEST_RETRIES_DEFAULT = 3 # Number of retries for fetching a page

# These will be populated by defaults or CLI arguments
URL_PATTERN = re.compile(URL_PATTERN_DEFAULT_STRING)
OUTPUT_FILE = OUTPUT_FILE_DEFAULT
OUTPUT_FILE_FULL = OUTPUT_FILE_FULL_DEFAULT
USER_AGENT = USER_AGENT_DEFAULT
OUTPUT_DIRECTORY = "" # Will be determined in __main__
LOG_FILE = LOG_FILE_DEFAULT
LLMS_TXT_SITE_SUMMARY = LLMS_TXT_SITE_SUMMARY_DEFAULT # Ensure it's defined before parse_arguments if used as default
REQUEST_DELAY = REQUEST_DELAY_DEFAULT
MAX_PAGES = MAX_PAGES_DEFAULT
EXCLUDED_URLS = [] # Will be populated by CLI arguments
SKIP_ADJACENT_REPETITIVE_PATHS = SKIP_ADJACENT_REPETITIVE_PATHS_DEFAULT
REQUEST_RETRIES = REQUEST_RETRIES_DEFAULT # Initialized with default, overridden by CLI

# Initialize logger
logger = logging.getLogger(__name__)

# Global state that persists across calls (e.g. for caching robots.txt)
robot_rules = {}  # {domain: RobotFileParser object}

# State per crawl, initialized in crawl()
visited_urls = set()
queue = []
discovered_pages_for_llms_txt = [] # Stores {'title': str, 'html_url': str, 'md_url': str or None, 'content_for_full_txt': str, 'content_source_type': str}

def get_robots_parser(domain):
    if domain not in robot_rules:
        from urllib.robotparser import RobotFileParser  # Imported here as per original snippet
        robots_url = f"https://{domain}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
        except Exception as e:
            logger.warning(f"Could not fetch or parse robots.txt for {domain}: {e}")
        robot_rules[domain] = parser
    return robot_rules[domain]

def is_allowed(url):
    parsed_url = urlparse(url)
    if not parsed_url.netloc: # Ensure domain exists
        return False
    parser = get_robots_parser(parsed_url.netloc)
    return parser.can_fetch(USER_AGENT, url)

def normalize_url(url):
    # Remove fragments and normalize
    parsed = urlparse(url)
    return parsed.scheme + "://" + parsed.netloc + parsed.path

def extract_main_content(html):
    # Readability for boilerplate removal
    doc = Document(html)
    return BeautifulSoup(doc.summary(), 'lxml').get_text(separator=' ', strip=True)

def extract_title_from_html(html_content, html_url_str=None): # Add optional url parameter
    if not html_content:
        return None
    try:
        soup = BeautifulSoup(html_content, 'lxml')
        title_tag = soup.find('title')
        if title_tag and title_tag.string:
            # Normalize whitespace and strip
            return re.sub(r'\s+', ' ', title_tag.string).strip()
    except Exception as e: # Capture the exception to log it
        logger.debug(f"Could not extract title from a page (URL: {html_url_str if html_url_str else 'unknown'}): {e}")
        pass
    return None

def check_for_md_version(html_url_str):
    """
    Checks for a corresponding .md version of an HTML page.
    - For /path/to/page.html, checks /path/to/page.html.md
    - For /path/to/page (no extension), checks /path/to/page.md
    - For /path/to/dir/, checks /path/to/dir/index.html.md
    """
    parsed_url = urlparse(html_url_str)
    path = parsed_url.path
    
    potential_md_urls = []
    if path.endswith('/'):
        md_path = path + "index.html.md"
        potential_md_urls.append(parsed_url._replace(path=md_path).geturl())
    else: # Covers both .html and no extension cases correctly for adding .md
        md_path = path + ".md"
        potential_md_urls.append(parsed_url._replace(path=md_path).geturl())

    for md_url in potential_md_urls:
        try:
            response = requests.head(md_url, headers={'User-Agent': USER_AGENT}, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                return md_url
        except requests.exceptions.RequestException:
            continue
    return None

def clean_text(text):
    # Remove excess whitespace, control characters, etc.
    text = re.sub(r'\s+', ' ', text)  # Collapse whitespace
    text = text.encode('ascii', 'ignore').decode('ascii').strip()  # Basic ASCII cleanup, ensuring ascii decode
    return text

def fetch_page(url):
    # Access the global REQUEST_RETRIES value, which is set from CLI or default
    global REQUEST_RETRIES
    
    for attempt in range(REQUEST_RETRIES + 1): # +1 because 0 retries means 1 attempt
        try:
            headers = {'User-Agent': USER_AGENT}
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
            return resp.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching {url} (Attempt {attempt + 1}/{REQUEST_RETRIES + 1}): {str(e)}")
            if attempt < REQUEST_RETRIES:
                time.sleep(REQUEST_DELAY * (attempt + 1)) # Simple backoff, or just REQUEST_DELAY
            else:
                logger.error(f"All {REQUEST_RETRIES + 1} attempts to fetch {url} failed.")
                return None
        except Exception as e: # Generic fallback for unexpected errors
            logger.error(f"Unexpected error fetching {url} (Attempt {attempt + 1}): {str(e)}")
            # Decide if you want to retry on generic exceptions or not
            # For now, we'll return None for non-RequestExceptions after the first try
            return None
    # Should not be reached if loop logic is correct, but as a fallback:
    return None

def extract_links(html, base_url):
    soup = BeautifulSoup(html, 'lxml')
    links = set()
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].split('#')[0]  # Remove anchors
        abs_url = urljoin(base_url, href)
        abs_url = normalize_url(abs_url) # Normalize after resolving
        if URL_PATTERN.match(abs_url) and abs_url not in visited_urls:
            # --- New: Check for >2 adjacent identical path segments (if enabled) ---
            if SKIP_ADJACENT_REPETITIVE_PATHS:
                path_segments_raw = urlparse(abs_url).path.strip('/').split('/')
                # Filter out empty segments that might result from multiple slashes like // or leading/trailing slashes
                path_segments = [segment for segment in path_segments_raw if segment]
                if len(path_segments) >= 3: # Need at least 3 non-empty segments to have 3 adjacent identical ones
                    for i in range(len(path_segments) - 2):
                        # Check for 3 adjacent identical non-empty segments
                        if path_segments[i] == path_segments[i+1] and \
                           path_segments[i+1] == path_segments[i+2]:
                            logger.warning(
                                f"Skipping URL due to >2 adjacent identical path segments ('{path_segments[i]}'): {abs_url}"
                            )
                            continue # Skip to the next a_tag in the outer loop

            # Check for excessive URL length
            if len(abs_url) > MAX_URL_LENGTH:
                logger.warning(f"Skipping excessively long URL ({len(abs_url)} chars): {abs_url[:150]}...") # Log a snippet
                continue

            # Check for excessive path segment repetition
            path_segments = urlparse(abs_url).path.strip('/').split('/')
            if len(path_segments) > 5: # Only check for longer paths
                last_segment = path_segments[-1]
                # Heuristic: if the last 3 segments are identical and the repeated segment is frequent
                if last_segment and \
                   len(path_segments) >= 3 and \
                   path_segments[-1] == path_segments[-2] == path_segments[-3] and \
                   path_segments.count(last_segment) > (len(path_segments) // 2):
                    logger.warning(f"Skipping URL with likely repetitive path segments: {abs_url}")
                    continue

            # Check if the URL matches any excluded patterns before adding
            excluded = False
            for pattern in EXCLUDED_URLS:
                if fnmatch.fnmatch(abs_url, pattern):
                    logger.info(f"Excluding link based on pattern '{pattern}': {abs_url}")
                    excluded = True
                    break # No need to check other patterns if one matches
            if not excluded: # Add only if not excluded
                links.add(abs_url)
    return links

def load_processed_urls_from_log(log_filepath):
    """Loads successfully fetched URLs from a previous crawler.log file."""
    visited = set()
    if not os.path.exists(log_filepath):
        logger.info(f"Restart: Log file '{log_filepath}' not found. Starting fresh.")
        return visited

    try:
        with open(log_filepath, 'r', encoding='utf-8') as f:
            # Regex to find lines indicating a successful fetch
            # Example log line: "2023-10-27 10:00:00,000 - INFO - crawler.crawl - Successfully fetched: https://example.com/page"
            # This pattern looks for "Successfully fetched: " followed by a URL.
            success_pattern = re.compile(r"Successfully fetched: (https?://[^\s]+)")
            for line in f:
                match = success_pattern.search(line) # Use search as the message might be embedded
                if match:
                    url = match.group(1)
                    visited.add(normalize_url(url)) # Normalize to be consistent
        if visited:
            logger.info(f"Restart: Loaded {len(visited)} successfully fetched URLs from log file: {log_filepath}")
        else:
            logger.info(f"Restart: No successfully fetched URLs found in log file: {log_filepath}. Starting fresh.")
    except Exception as e:
        logger.error(f"Restart: Error loading processed URLs from log '{log_filepath}': {e}. Starting fresh.")
        return set() # Return empty set on error
    return visited

def crawl(restart_mode=False):
    global visited_urls, queue, discovered_pages_for_llms_txt, robot_rules

    # Initialize state for this specific crawl run
    # robot_rules is a cache and is not reset here.
    visited_urls = set()
    queue = [BASE_URL] # Use the potentially overridden BASE_URL
    discovered_pages_for_llms_txt = [] # Reset if crawl is called multiple times


    # Initialize tqdm with MAX_PAGES as the total, it's an upper bound.
    pbar = tqdm(total=MAX_PAGES, desc="Crawling pages", unit="page")

    if restart_mode:
        visited_urls.update(load_processed_urls_from_log(LOG_FILE)) # Use LOG_FILE now
        pbar.total = max(0, MAX_PAGES - len(visited_urls)) # Adjust tqdm total if restarting

    processed_pages_count = 0 # To ensure pbar doesn't update beyond MAX_PAGES

    while queue and len(visited_urls) < MAX_PAGES and processed_pages_count < MAX_PAGES:
        url = queue.pop(0)
        if url in visited_urls:
            continue

        if not is_allowed(url):
            # Optionally, add to visited_urls here to prevent re-checking robots.txt
            # visited_urls.add(url) 
            logger.info(f"Skipped (robots.txt): {url}")
            # tqdm.write(f"Skipped (robots.txt): {url}") # For logging without breaking bar
            continue

        visited_urls.add(url)
        pbar.set_description_str(f"Crawling {url[:50]}...") # Show current URL being processed

        html = fetch_page(url)
        if not html:
            logger.warning(f"Fetch returned no HTML for {url} after retries.")
            time.sleep(REQUEST_DELAY) # Still delay if fetch failed
            continue
        logger.info(f"Successfully fetched: {url}")

        # --- Content Acquisition for llms.txt and llms-full.txt ---
        page_title = extract_title_from_html(html, url) or url # Pass URL for logging context
        md_url = check_for_md_version(url) # This function also uses USER_AGENT
        content_for_full_txt = ""
        page_content_source_type = "" # 'md', 'html', or empty

        if md_url:
            raw_md_content = fetch_page(md_url)
            if raw_md_content:
                content_for_full_txt = raw_md_content.replace('\r\n', '\n').strip() # Keep as Markdown
                page_content_source_type = 'md'
                logger.info(f"Using Markdown content from {md_url}")
            else:
                logger.warning(f"Failed to fetch Markdown content from {md_url}, will try HTML from original URL.")

        if not content_for_full_txt and html: # Fallback to HTML if MD failed or not present
            # extract_main_content uses readability and gets plain text
            main_html_text_content = extract_main_content(html)
            # Further whitespace normalization
            content_for_full_txt = re.sub(r'\s+', ' ', main_html_text_content).strip()
            page_content_source_type = 'html'
            logger.info(f"Using extracted HTML content from {url}")
        
        discovered_pages_for_llms_txt.append({
            'title': page_title, 'html_url': url, 'md_url': md_url,
            'content_for_full_txt': content_for_full_txt,
            'content_source_type': page_content_source_type
        })

        new_links = extract_links(html, url)
        for link in new_links:
            if link not in visited_urls and link not in queue:
                # Add to queue only if we haven't hit overall page limits for processing
                if (len(visited_urls) + len(queue)) < MAX_PAGES * 1.5: # Heuristic to avoid overly large queue
                    queue.append(link)
        
        pbar.update(1)
        processed_pages_count += 1
        time.sleep(REQUEST_DELAY)
        
    pbar.close()

    # --- llms.txt (index file) generation ---
    llms_content_parts = []
    llms_content_parts.append(f"# {LLMS_TXT_SITE_TITLE}\n\n")
    llms_content_parts.append(f"> {LLMS_TXT_SITE_SUMMARY}\n\n")
    llms_content_parts.append(f"{LLMS_TXT_DETAILS_PLACEHOLDER}\n\n")

    if discovered_pages_for_llms_txt:
        llms_content_parts.append("## Discovered Pages\n\n") # You might want more specific H2 sections
        for page_info in discovered_pages_for_llms_txt:
            # Prioritize .md URL if available
            link_url_to_use = page_info['md_url'] if page_info['md_url'] else page_info['html_url']
            # Sanitize title for Markdown link (basic sanitization)
            link_title_sanitized = page_info['title'].replace('[', '(').replace(']', ')')
            
            description = " (Markdown version link)" if page_info['md_url'] else " (HTML page link)"
            llms_content_parts.append(f"- [{link_title_sanitized}]({link_url_to_use}): Source{description}\n") # Single newline for compact list
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        outfile.write("".join(llms_content_parts)) # Join without extra newlines, they are in parts

    # --- llms-full.txt (full content file) generation ---
    if discovered_pages_for_llms_txt:
        with open(OUTPUT_FILE_FULL, 'w', encoding='utf-8') as outfile_full:
            outfile_full.write(f"# {LLMS_TXT_SITE_TITLE}\n\n")
            outfile_full.write(f"> {LLMS_TXT_SITE_SUMMARY}\n\n")
            outfile_full.write(f"{LLMS_TXT_DETAILS_PLACEHOLDER}\n\n")

            outfile_full.write("## Discovered Pages Content\n\n")
            for page_info in discovered_pages_for_llms_txt:
                link_url_to_use = page_info['md_url'] if page_info['md_url'] else page_info['html_url']
                link_title_sanitized = page_info['title'].replace('[', '(').replace(']', ')')

                content_desc = ""
                if page_info['content_source_type'] == 'md':
                    content_desc = " (Content from Markdown source)"
                elif page_info['content_source_type'] == 'html':
                    content_desc = " (Content extracted from HTML)"
                
                outfile_full.write(f"- [{link_title_sanitized}]({link_url_to_use}): Source{content_desc}\n\n")
                if page_info['content_for_full_txt']:
                    outfile_full.write(f"{page_info['content_for_full_txt']}\n\n")
                else:
                    outfile_full.write("(Content not available or fetch failed for this page)\n\n")

def parse_arguments(log_file_default_val, site_summary_default_val):
    epilog_text = textwrap.dedent(r"""\
    Example usage:
      Crawl llmstxt.org (default configuration if these match):
        %(prog)s --base-url "https://llmstxt.org/" \\
                   --url-pattern "^https?://llmstxt\.org/" \
                   --site-title "LLMs.txt Project"

      Crawl a different site:
        %(prog)s --base-url "https://docs.example.com/" \\
                   --url-pattern "^https?://docs\.example\.com/" \
                   --site-title "Example Docs" --output-file "example_llms.txt"
    """)
    parser = argparse.ArgumentParser(
        description="Crawl a documentation website to produce an llms.txt file.",
        formatter_class=argparse.RawTextHelpFormatter, # To allow for formatted epilog
        epilog=epilog_text
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["NONE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level. (Currently only prints the selection)"
    )
    parser.add_argument(
        "--base-url", type=str,
        required=True, help="The root URL of the documentation to crawl (e.g., https://example.com/docs)."
    )
    parser.add_argument(
        "--url-pattern", type=str,
        required=True, help=r"Regex pattern (as a string) to match documentation URLs (e.g., \"^https?://example\.com/docs/\")."
    )
    parser.add_argument(
        "--output-file", type=str,
        default=OUTPUT_FILE_DEFAULT, help="Name for the llms.txt index file."
    )
    parser.add_argument(
        "--output-file-full", type=str,
        default=OUTPUT_FILE_FULL_DEFAULT, help="Name for the llms-full.txt content file."
    )
    parser.add_argument(
        "--output-directory", type=str,
        help=f"Directory to store output files. Default: {OUTPUT_DIRECTORY_DEFAULT_BASE}/<fqdn_of_base_url>/"
    )
    parser.add_argument(
        "--output-type", type=str,
        default="txt", choices=["txt", "md", "json", "xml"],
        help="Desired output type. Affects default file extensions if --output-file/--output-file-full are not set. (Content generation for json/xml not yet implemented)"
    )
    parser.add_argument(
        "--log-file", type=str,
        default=log_file_default_val, help="Name for the log file."
    )
    parser.add_argument(
        "--user-agent", type=str,
        default=USER_AGENT_DEFAULT, help="User-Agent string for crawling."
    )
    parser.add_argument(
        "--request-delay", type=int,
        default=REQUEST_DELAY_DEFAULT, help="Delay in seconds between requests."
    )
    parser.add_argument(
        "--max-pages", type=int,
        default=MAX_PAGES_DEFAULT, help="Maximum number of pages to crawl."
    )
    parser.add_argument(
        "--retries", type=int,
        default=REQUEST_RETRIES_DEFAULT, help="Number of retries for fetching a page in case of an error."
    )
    parser.add_argument(
        "--excluded-url", action='append', default=[],
        help="URL pattern (supports wildcards like *) to exclude from crawling. "
             "Can be specified multiple times to exclude several patterns (e.g., --excluded-url \"*/api/*\" --excluded-url \"*.pdf\")."
    )
    parser.add_argument(
        "--site-title", type=str,
        required=True, help="Site title for the H1 in generated files (e.g., \"My Project Documentation\")."
    )
    parser.add_argument(
        "--site-summary", type=str,
        default=site_summary_default_val, help="Site summary for the blockquote in llms.txt."
    )
    parser.add_argument(
        "--details-placeholder", type=str,
        help="Text for the 'Optional details' section in llms.txt. If not set, this section will be empty."
    )
    parser.add_argument(
        "--restart", action="store_true",
        help="Restart a previous crawl, skipping pages logged as 'Successfully fetched' in the existing log file."
    )
    parser.add_argument(
        "--skip-adjacent-repetitive-paths", action="store_true",
        default=SKIP_ADJACENT_REPETITIVE_PATHS_DEFAULT,
        help="Skip URLs with more than two adjacent identical path segments (e.g., /word/word/word/). Default: False"
    )
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments(LOG_FILE_DEFAULT, LLMS_TXT_SITE_SUMMARY_DEFAULT) # Pass defaults

    # --- Setup Logging ---
    log_level_str = args.log_level.upper()
    numeric_log_level = getattr(logging, log_level_str, logging.INFO) # Default to INFO if invalid

    # Configure file handler
    LOG_FILE = args.log_file # Set global LOG_FILE from args
    file_handler = logging.FileHandler(LOG_FILE, mode='w', encoding='utf-8') # Overwrite log file each run
    
    # Determine the effective log level for the file handler
    # If console is NONE, file still logs at least INFO. Otherwise, use the specified level.
    file_log_level = numeric_log_level
    if log_level_str == "NONE":
        file_log_level = logging.INFO 

    file_handler.setLevel(file_log_level)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s.%(funcName)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    
    # Configure the logger (used throughout the script)
    logger.addHandler(file_handler)
    # Set logger's own level to the most verbose of its handlers or the desired level
    logger.setLevel(min(file_log_level, logging.DEBUG)) # Allow DEBUG messages if handler is set to DEBUG

    # Set mandatory configurations from CLI arguments
    BASE_URL = args.base_url
    URL_PATTERN = re.compile(args.url_pattern)
    LLMS_TXT_SITE_TITLE = args.site_title

    # Determine and create output directory
    if args.output_directory:
        OUTPUT_DIRECTORY = args.output_directory
    else:
        try:
            fqdn = urlparse(BASE_URL).netloc
            if not fqdn: # Should not happen with a valid BASE_URL
                fqdn = "unknown_site"
            OUTPUT_DIRECTORY = os.path.join(OUTPUT_DIRECTORY_DEFAULT_BASE, fqdn)
        except Exception as e:
            logger.error(f"Could not parse FQDN from BASE_URL '{BASE_URL}': {e}. Using default output base.")
            OUTPUT_DIRECTORY = OUTPUT_DIRECTORY_DEFAULT_BASE
    
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    logger.info(f"Output directory set to: {os.path.abspath(OUTPUT_DIRECTORY)}")

    # Set optional configurations from CLI arguments or their initial defaults
    OUTPUT_FILE = os.path.join(OUTPUT_DIRECTORY, args.output_file)
    OUTPUT_FILE_FULL = os.path.join(OUTPUT_DIRECTORY, args.output_file_full)
    USER_AGENT = args.user_agent
    LOG_FILE = os.path.join(OUTPUT_DIRECTORY, args.log_file) # Update LOG_FILE path
    LLMS_TXT_SITE_SUMMARY = args.site_summary
    LLMS_TXT_DETAILS_PLACEHOLDER = args.details_placeholder if args.details_placeholder is not None else ""
    REQUEST_DELAY = args.request_delay
    REQUEST_RETRIES = args.retries 
    EXCLUDED_URLS = args.excluded_url 
    MAX_PAGES = args.max_pages
    SKIP_ADJACENT_REPETITIVE_PATHS = args.skip_adjacent_repetitive_paths

    # Adjust default output file extensions based on --output-type if filenames were not explicitly set
    if args.output_type != "txt":
        new_extension = f".{args.output_type}"
        # Check if the output file name is still its original default
        if OUTPUT_FILE == OUTPUT_FILE_DEFAULT:
            base, old_ext = os.path.splitext(OUTPUT_FILE)
            if old_ext.lower() == ".txt": # Only change if it was the .txt default
                OUTPUT_FILE = base + new_extension
        
        if OUTPUT_FILE_FULL == OUTPUT_FILE_FULL_DEFAULT:
            base_full, old_ext_full = os.path.splitext(OUTPUT_FILE_FULL)
            if old_ext_full.lower() == ".txt": # Only change if it was the .txt default
                OUTPUT_FILE_FULL = base_full + new_extension

    # Initial messages will go to the log file
    if args.log_level != "NONE": # This print was for immediate console feedback before logger was fully set up
        logger.info(f"Console log output level set to: {args.log_level}")
    logger.info(f"Detailed logs will be written to: {LOG_FILE}")
    logger.info(f"File log level set to: {logging.getLevelName(file_log_level)}")
    logger.info(f"Excluded URL patterns: {EXCLUDED_URLS if EXCLUDED_URLS else 'None'}")
    logger.info(f"Starting crawl from {BASE_URL}. Index output: {OUTPUT_FILE}, Full content output: {OUTPUT_FILE_FULL}")
    crawl(restart_mode=args.restart)
    logger.info(f"Completed! Crawled {len(visited_urls)} pages.")
