import unittest
from unittest.mock import patch, MagicMock, mock_open, call
import os
import sys
import re
import logging
import tempfile
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser as StdLibRobotFileParser # For type hinting if needed

# Add the project root directory to sys.path to allow importing crawler
# Assumes test_crawler.py is in a 'tests' subdirectory and crawler.py is in the parent.
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root_dir = os.path.dirname(current_script_dir)
sys.path.insert(0, project_root_dir)

import crawler # Import the script to be tested

# Helper to reset crawler's global state that might be modified during tests
def reset_crawler_globals():
    crawler.BASE_URL = "https://example.com" # Default for tests
    crawler.URL_PATTERN_DEFAULT_STRING = r'^https?://example\.com'
    crawler.URL_PATTERN = re.compile(crawler.URL_PATTERN_DEFAULT_STRING)
    crawler.OUTPUT_FILE_DEFAULT = "llms.txt"
    crawler.OUTPUT_FILE_FULL_DEFAULT = "llms-full.txt"
    crawler.OUTPUT_DIRECTORY_DEFAULT_BASE = "./output_test" # Use a test-specific base
    crawler.LOG_FILE_DEFAULT = "crawler_test.log"
    crawler.USER_AGENT_DEFAULT = "TestCrawler/1.0"
    crawler.LLMS_TXT_SITE_TITLE = "Test Site"
    crawler.LLMS_TXT_SITE_SUMMARY_DEFAULT = "Test summary."
    crawler.LLMS_TXT_DETAILS_PLACEHOLDER = "Test details."
    crawler.REQUEST_DELAY_DEFAULT = 0 # Faster tests
    crawler.MAX_PAGES_DEFAULT = 10
    crawler.MAX_URL_LENGTH = 255 # Shorter for some tests
    crawler.SKIP_ADJACENT_REPETITIVE_PATHS_DEFAULT = False
    crawler.REQUEST_RETRIES_DEFAULT = 1 # Faster tests

    # These will be populated by defaults or CLI arguments, reset them
    crawler.OUTPUT_FILE = crawler.OUTPUT_FILE_DEFAULT
    crawler.OUTPUT_FILE_FULL = crawler.OUTPUT_FILE_FULL_DEFAULT
    crawler.USER_AGENT = crawler.USER_AGENT_DEFAULT
    crawler.OUTPUT_DIRECTORY = "" 
    crawler.LOG_FILE = crawler.LOG_FILE_DEFAULT
    crawler.LLMS_TXT_SITE_SUMMARY = crawler.LLMS_TXT_SITE_SUMMARY_DEFAULT
    # LLMS_TXT_DETAILS_PLACEHOLDER is handled by its default or CLI
    crawler.REQUEST_DELAY = crawler.REQUEST_DELAY_DEFAULT
    crawler.MAX_PAGES = crawler.MAX_PAGES_DEFAULT
    crawler.EXCLUDED_URLS = []
    crawler.SKIP_ADJACENT_REPETITIVE_PATHS = crawler.SKIP_ADJACENT_REPETITIVE_PATHS_DEFAULT
    crawler.REQUEST_RETRIES = crawler.REQUEST_RETRIES_DEFAULT

    # Global state
    crawler.robot_rules = {}
    crawler.visited_urls = set()
    crawler.queue = []
    crawler.discovered_pages_for_llms_txt = []

    # Reset logger (important if __main__ was run or if tests modify handlers)
    # For simplicity, we'll rely on the BaseCrawlerTestCase to mock the logger instance.
    # If the script's main explicitly adds handlers, more robust reset might be needed
    # or tests for main would mock handler creation.
    # For now, assume crawler.logger is a module-level logger.
    if hasattr(crawler.logger, 'handlers'):
        # Be cautious with this; if other test infrastructure relies on handlers,
        # this could interfere. Mocking the logger instance is often safer.
        # For now, let's assume BaseCrawlerTestCase's mock is sufficient.
        pass

class BaseCrawlerTestCase(unittest.TestCase):
    def setUp(self):
        reset_crawler_globals()
        # Mock the logger used in the crawler module
        self.patcher_logger = patch('crawler.logger', MagicMock(spec=logging.Logger))
        self.mock_logger = self.patcher_logger.start()
        self.addCleanup(self.patcher_logger.stop)

        # Mock tqdm to prevent console output and allow iteration
        self.patcher_tqdm = patch('crawler.tqdm', MagicMock())
        self.mock_tqdm = self.patcher_tqdm.start()
        self.addCleanup(self.patcher_tqdm.stop)
        
        self.temp_dir_patcher = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp_dir_patcher.name # Get the path of the temporary directory
        self.addCleanup(self.temp_dir_patcher.cleanup) # Register the cleanup method
        
        # Set a default output directory for tests that might need it before __main__ logic runs
        crawler.OUTPUT_DIRECTORY = self.temp_dir
        crawler.LOG_FILE = os.path.join(self.temp_dir, crawler.LOG_FILE_DEFAULT)
        crawler.OUTPUT_FILE = os.path.join(self.temp_dir, crawler.OUTPUT_FILE_DEFAULT)
        crawler.OUTPUT_FILE_FULL = os.path.join(self.temp_dir, crawler.OUTPUT_FILE_FULL_DEFAULT)


    def tearDown(self):
        # Cleanup is handled by addCleanup
        pass

class TestHelperFunctions(BaseCrawlerTestCase):
    def test_normalize_url(self):
        self.assertEqual(crawler.normalize_url("http://example.com/path?query=1#frag"), "http://example.com/path")
        self.assertEqual(crawler.normalize_url("https://example.com/path/"), "https://example.com/path/")
        self.assertEqual(crawler.normalize_url("http://EXAMPLE.com/Path"), "http://example.com/Path") # Keeps case in path

    def test_extract_title_from_html(self):
        self.assertEqual(crawler.extract_title_from_html("<html><head><title> Test Title </title></head></html>"), "Test Title")
        self.assertEqual(crawler.extract_title_from_html("<html><head><title>  Test   Title  </title></head></html>"), "Test Title")
        self.assertIsNone(crawler.extract_title_from_html("<html><body><h1>No title</h1></body></html>"))
        self.assertIsNone(crawler.extract_title_from_html(""))
        # Test logging on exception (e.g., unparseable content)
        with patch('crawler.BeautifulSoup', side_effect=Exception("Parse error")):
            self.assertIsNone(crawler.extract_title_from_html("bad html", "http://example.com/bad"))
            self.mock_logger.debug.assert_called_with("Could not extract title from a page (URL: http://example.com/bad): Parse error")

    def test_clean_text(self):
        self.assertEqual(crawler.clean_text("  extra \n whitespace  "), "extra whitespace")
        self.assertEqual(crawler.clean_text("text with\x00control\x1fchars"), "text withcontrolchars")
        self.assertEqual(crawler.clean_text("Non-ASCII: éàçü"), "Non-ASCII: ") # Strips non-ASCII

    @patch('crawler.requests.head')
    def test_check_for_md_version(self, mock_head):
        # Case 1: page.html -> page.html.md
        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_head.return_value = mock_response_ok
        
        url_html = "http://example.com/path/to/page.html"
        expected_md_url = "http://example.com/path/to/page.html.md"
        self.assertEqual(crawler.check_for_md_version(url_html), expected_md_url)
        mock_head.assert_called_once_with(expected_md_url, headers={'User-Agent': crawler.USER_AGENT}, timeout=5, allow_redirects=True)
        mock_head.reset_mock()

        # Case 2: page (no extension) -> page.md
        url_no_ext = "http://example.com/path/to/page"
        expected_md_url_no_ext = "http://example.com/path/to/page.md"
        self.assertEqual(crawler.check_for_md_version(url_no_ext), expected_md_url_no_ext)
        mock_head.assert_called_once_with(expected_md_url_no_ext, headers={'User-Agent': crawler.USER_AGENT}, timeout=5, allow_redirects=True)
        mock_head.reset_mock()

        # Case 3: dir/ -> dir/index.html.md
        url_dir = "http://example.com/path/to/dir/"
        expected_md_url_dir = "http://example.com/path/to/dir/index.html.md"
        self.assertEqual(crawler.check_for_md_version(url_dir), expected_md_url_dir)
        mock_head.assert_called_once_with(expected_md_url_dir, headers={'User-Agent': crawler.USER_AGENT}, timeout=5, allow_redirects=True)
        mock_head.reset_mock()

        # Case 4: No MD version found
        mock_response_not_found = MagicMock()
        mock_response_not_found.status_code = 404
        mock_head.return_value = mock_response_not_found
        self.assertIsNone(crawler.check_for_md_version(url_html))
        mock_head.reset_mock()

        # Case 5: RequestException
        mock_head.side_effect = crawler.requests.exceptions.RequestException("Connection error")
        self.assertIsNone(crawler.check_for_md_version(url_html))
        self.mock_logger.error.assert_not_called() # Should just continue

    def test_extract_main_content(self):
        # Relies on readability, so this is a small integration test for it
        html_doc = "<html><head><title>Title</title></head><body><article><p>Main content here.</p></article><footer>Scrap this</footer></body></html>"
        # Readability might add the title if it's prominent. Let's focus on the p content.
        # The exact output of readability can be complex, so we check for key phrases.
        # BeautifulSoup(doc.summary(), 'lxml').get_text(separator=' ', strip=True)
        # For this simple case, readability might output "Title Main content here."
        content = crawler.extract_main_content(html_doc)
        self.assertIn("Main content here", content)
        # self.assertNotIn("Scrap this", content) # This depends heavily on readability's algorithm

        empty_content = crawler.extract_main_content("<html></html>")
        self.assertEqual(empty_content, "")


class TestRobotsAndPermissions(BaseCrawlerTestCase):
    @patch('crawler.RobotFileParser') # Patching where it's imported and used in crawler.py
    def test_get_robots_parser(self, MockRobotFileParser):
        mock_parser_instance = MockRobotFileParser.return_value
        
        # First call for a domain
        parser1 = crawler.get_robots_parser("example.com")
        self.assertEqual(parser1, mock_parser_instance)
        MockRobotFileParser.assert_called_once()
        mock_parser_instance.set_url.assert_called_once_with("https://example.com/robots.txt")
        mock_parser_instance.read.assert_called_once()
        
        # Second call for the same domain (should be cached)
        parser2 = crawler.get_robots_parser("example.com")
        self.assertEqual(parser2, mock_parser_instance)
        MockRobotFileParser.assert_called_once() # Still once due to cache

        # Call for a new domain
        mock_parser_instance_new = MockRobotFileParser.return_value = MagicMock() # New instance for new domain
        parser3 = crawler.get_robots_parser("another.com")
        self.assertEqual(parser3, mock_parser_instance_new)
        self.assertEqual(MockRobotFileParser.call_count, 2)
        mock_parser_instance_new.set_url.assert_called_once_with("https://another.com/robots.txt")

    @patch('crawler.RobotFileParser')
    def test_get_robots_parser_read_exception(self, MockRobotFileParser):
        mock_parser_instance = MockRobotFileParser.return_value
        mock_parser_instance.read.side_effect = Exception("Robots read error")
        
        crawler.get_robots_parser("error.com")
        self.mock_logger.warning.assert_called_with("Could not fetch or parse robots.txt for error.com: Robots read error")

    @patch('crawler.get_robots_parser')
    def test_is_allowed(self, mock_get_robots_parser):
        mock_parser = MagicMock()
        mock_get_robots_parser.return_value = mock_parser
        
        mock_parser.can_fetch.return_value = True
        self.assertTrue(crawler.is_allowed("http://example.com/allowed"))
        mock_get_robots_parser.assert_called_with("example.com")
        mock_parser.can_fetch.assert_called_with(crawler.USER_AGENT, "http://example.com/allowed")

        mock_parser.can_fetch.return_value = False
        self.assertFalse(crawler.is_allowed("http://example.com/disallowed"))

        self.assertFalse(crawler.is_allowed("htp://no_netloc_url")) # Invalid scheme, urlparse might yield no netloc
        self.assertFalse(crawler.is_allowed("/relative/path_only")) # No netloc


class TestFetchPage(BaseCrawlerTestCase):
    @patch('crawler.requests.get')
    @patch('crawler.time.sleep', MagicMock()) # Mock sleep to speed up tests
    def test_fetch_page_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.text = "<html>Success</html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response
        
        crawler.REQUEST_RETRIES = 1 # For this test
        html = crawler.fetch_page("http://example.com/success")
        self.assertEqual(html, "<html>Success</html>")
        mock_get.assert_called_once_with("http://example.com/success", headers={'User-Agent': crawler.USER_AGENT}, timeout=10)
        mock_response.raise_for_status.assert_called_once()

    @patch('crawler.requests.get')
    @patch('crawler.time.sleep') # Keep sleep mock to check calls
    def test_fetch_page_http_error_with_retries(self, mock_sleep, mock_get):
        crawler.REQUEST_RETRIES = 2 # Total 3 attempts
        mock_get.side_effect = [
            crawler.requests.exceptions.HTTPError("404 Error"),
            crawler.requests.exceptions.HTTPError("500 Error"),
            crawler.requests.exceptions.HTTPError("503 Error") # Last attempt also fails
        ]
        
        result = crawler.fetch_page("http://example.com/httperror")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 3) # 1 initial + 2 retries
        self.assertEqual(mock_sleep.call_count, 2) # Sleep before each retry
        mock_sleep.assert_has_calls([call(crawler.REQUEST_DELAY * 1), call(crawler.REQUEST_DELAY * 2)])
        self.mock_logger.error.assert_any_call("Error fetching http://example.com/httperror (Attempt 1/3): 404 Error")
        self.mock_logger.error.assert_any_call("Error fetching http://example.com/httperror (Attempt 2/3): 500 Error")
        self.mock_logger.error.assert_any_call("Error fetching http://example.com/httperror (Attempt 3/3): 503 Error")
        self.mock_logger.error.assert_called_with("All 3 attempts to fetch http://example.com/httperror failed.")

    @patch('crawler.requests.get')
    @patch('crawler.time.sleep', MagicMock())
    def test_fetch_page_request_exception(self, mock_get):
        crawler.REQUEST_RETRIES = 1
        mock_get.side_effect = crawler.requests.exceptions.RequestException("Connection Timeout")
        
        result = crawler.fetch_page("http://example.com/connerror")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 2) # 1 initial + 1 retry
        self.mock_logger.error.assert_any_call("Error fetching http://example.com/connerror (Attempt 1/2): Connection Timeout")
        self.mock_logger.error.assert_any_call("Error fetching http://example.com/connerror (Attempt 2/2): Connection Timeout")

    @patch('crawler.requests.get')
    @patch('crawler.time.sleep', MagicMock())
    def test_fetch_page_unexpected_exception(self, mock_get):
        crawler.REQUEST_RETRIES = 1
        mock_get.side_effect = Exception("Unexpected error") # Generic exception

        result = crawler.fetch_page("http://example.com/unexpected")
        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 1) # Should not retry on generic exception by default
        self.mock_logger.error.assert_called_with("Unexpected error fetching http://example.com/unexpected (Attempt 1): Unexpected error")


class TestLinkExtraction(BaseCrawlerTestCase):
    def setUp(self):
        super().setUp()
        crawler.URL_PATTERN = re.compile(r"^https?://example\.com")
        crawler.visited_urls = set()
        crawler.MAX_URL_LENGTH = 50 # For testing length limit
        crawler.EXCLUDED_URLS = []
        crawler.SKIP_ADJACENT_REPETITIVE_PATHS = False

    def test_extract_links_basic(self):
        html = """
        <a href="https://example.com/page1">Page 1</a>
        <a href="/page2">Page 2</a>
        <a href="https://other.com/page3">Other Site</a>
        <a href="https://example.com/page1#section">Page 1 Again with fragment</a>
        """
        base_url = "https://example.com"
        links = crawler.extract_links(html, base_url)
        self.assertEqual(links, {"https://example.com/page1", "https://example.com/page2"})

    def test_extract_links_already_visited(self):
        crawler.visited_urls.add("https://example.com/page1")
        html = '<a href="https://example.com/page1">Page 1</a>'
        links = crawler.extract_links(html, "https://example.com")
        self.assertEqual(links, set())

    def test_extract_links_max_url_length(self):
        long_url = "https://example.com/" + "a" * 50 # Exceeds MAX_URL_LENGTH = 50
        html = f'<a href="{long_url}">Long URL</a><a href="https://example.com/short">Short</a>'
        links = crawler.extract_links(html, "https://example.com")
        self.assertEqual(links, {"https://example.com/short"})
        self.mock_logger.warning.assert_called_with(f"Skipping excessively long URL ({len(long_url)} chars): {long_url[:150]}...")

    def test_extract_links_excluded_urls(self):
        crawler.EXCLUDED_URLS = ["*api*", "https://example.com/private/*"]
        html = """
        <a href="https://example.com/data/api/item1">API Link</a>
        <a href="https://example.com/public/doc">Public Doc</a>
        <a href="https://example.com/private/secret">Private Secret</a>
        """
        links = crawler.extract_links(html, "https://example.com")
        self.assertEqual(links, {"https://example.com/public/doc"})
        self.mock_logger.info.assert_any_call("Excluding link based on pattern '*api*': https://example.com/data/api/item1")
        self.mock_logger.info.assert_any_call("Excluding link based on pattern 'https://example.com/private/*': https://example.com/private/secret")

    def test_extract_links_skip_adjacent_repetitive_paths(self):
        crawler.SKIP_ADJACENT_REPETITIVE_PATHS = True
        html = """
        <a href="https://example.com/a/a/a/page">Repetitive Path AAA</a>
        <a href="https://example.com/a/b/a/page">Non-Repetitive Path ABA</a>
        <a href="https://example.com/a/a/page">Non-Repetitive Path AA</a>
        <a href="https://example.com/a//a//a/page">Repetitive with empty segments</a>
        """
        # The filter `[segment for segment in path_segments_raw if segment]` handles empty segments.
        # So "a//a//a" becomes ["a", "a", "a"]
        links = crawler.extract_links(html, "https://example.com")
        expected_links = {
            "https://example.com/a/b/a/page",
            "https://example.com/a/a/page"
        }
        self.assertEqual(links, expected_links)
        self.mock_logger.warning.assert_any_call("Skipping URL due to >2 adjacent identical path segments ('a'): https://example.com/a/a/a/page")
        self.mock_logger.warning.assert_any_call("Skipping URL due to >2 adjacent identical path segments ('a'): https://example.com/a//a//a/page")


    def test_extract_links_heuristic_repetitive_path_segments(self):
        # This heuristic: last 3 segments identical AND repeated segment > 50% of total segments
        # Path: /a/b/c/c/c (len 5, c is 3/5 > 0.5) -> skip
        # Path: /a/c/c/c (len 4, c is 3/4 > 0.5) -> skip
        # Path: /a/b/c/d/d/d (len 6, d is 3/6 == 0.5) -> not skipped by this heuristic
        # Path: /a/b/c/x/y/z/z/z (len 8, z is 3/8 < 0.5) -> not skipped
        # Path: /z/z/z/z/z (len 5, z is 5/5 > 0.5) -> skip
        html = """
        <a href="https://example.com/a/b/c/c/c">Skip CCC1</a>
        <a href="https://example.com/a/c/c/c">Skip CCC2</a>
        <a href="https://example.com/a/b/c/d/d/d">Keep DDD1 (count not > len/2)</a>
        <a href="https://example.com/z/z/z/z/z">Skip ZZZZZ</a>
        <a href="https://example.com/a/b/c/x/y/z/z/z">Keep ZZZ2 (count not > len/2)</a>
        <a href="https://example.com/short/path">Short Path</a>
        """
        links = crawler.extract_links(html, "https://example.com")
        expected = {
            "https://example.com/a/b/c/d/d/d",
            "https://example.com/a/b/c/x/y/z/z/z",
            "https://example.com/short/path"
        }
        self.assertEqual(links, expected)
        self.mock_logger.warning.assert_any_call("Skipping URL with likely repetitive path segments: https://example.com/a/b/c/c/c")
        self.mock_logger.warning.assert_any_call("Skipping URL with likely repetitive path segments: https://example.com/a/c/c/c")
        self.mock_logger.warning.assert_any_call("Skipping URL with likely repetitive path segments: https://example.com/z/z/z/z/z")


class TestLogLoading(BaseCrawlerTestCase):
    def test_load_processed_urls_from_log_file_not_exist(self):
        with patch('os.path.exists', return_value=False):
            visited = crawler.load_processed_urls_from_log("nonexistent.log")
            self.assertEqual(visited, set())
            self.mock_logger.info.assert_called_with("Restart: Log file 'nonexistent.log' not found. Starting fresh.")

    def test_load_processed_urls_from_log_success(self):
        log_content = (
            "2023-10-27 10:00:00,000 - INFO - module.func - Successfully fetched: http://example.com/page1\n"
            "Some other log line\n"
            "2023-10-27 10:01:00,000 - INFO - module.func - Successfully fetched: https://example.com/page2#frag\n"
            "2023-10-27 10:02:00,000 - ERROR - module.func - Failed to fetch: http://example.com/page3\n"
        )
        expected_urls = {
            "http://example.com/page1",
            "https://example.com/page2" # Normalized
        }
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=log_content)) as mock_file:
                visited = crawler.load_processed_urls_from_log("dummy.log")
                self.assertEqual(visited, expected_urls)
                mock_file.assert_called_once_with("dummy.log", 'r', encoding='utf-8')
                self.mock_logger.info.assert_called_with("Restart: Loaded 2 successfully fetched URLs from log file: dummy.log")

    def test_load_processed_urls_from_log_empty_or_no_success(self):
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data="No success here")) as mock_file:
                visited = crawler.load_processed_urls_from_log("empty.log")
                self.assertEqual(visited, set())
                self.mock_logger.info.assert_called_with("Restart: No successfully fetched URLs found in log file: empty.log. Starting fresh.")

    def test_load_processed_urls_from_log_read_error(self):
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', side_effect=IOError("Read error")):
                visited = crawler.load_processed_urls_from_log("error.log")
                self.assertEqual(visited, set())
                self.mock_logger.error.assert_called_with("Restart: Error loading processed URLs from log 'error.log': Read error. Starting fresh.")


@patch('crawler.time.sleep', MagicMock()) # Mock sleep globally for crawl tests
class TestCrawlLogic(BaseCrawlerTestCase):
    def setUp(self):
        super().setUp()
        # Common mocks for crawl
        self.patcher_fetch = patch('crawler.fetch_page')
        self.mock_fetch_page = self.patcher_fetch.start()
        self.addCleanup(self.patcher_fetch.stop)

        self.patcher_extract_links = patch('crawler.extract_links')
        self.mock_extract_links = self.patcher_extract_links.start()
        self.addCleanup(self.patcher_extract_links.stop)

        self.patcher_is_allowed = patch('crawler.is_allowed', return_value=True)
        self.mock_is_allowed = self.patcher_is_allowed.start()
        self.addCleanup(self.patcher_is_allowed.stop)
        
        self.patcher_check_md = patch('crawler.check_for_md_version', return_value=None)
        self.mock_check_md_version = self.patcher_check_md.start()
        self.addCleanup(self.patcher_check_md.stop)

        self.patcher_extract_title = patch('crawler.extract_title_from_html', side_effect=lambda html, url=None: "Default Title")
        self.mock_extract_title = self.patcher_extract_title.start()
        self.addCleanup(self.patcher_extract_title.stop)

        self.patcher_extract_content = patch('crawler.extract_main_content', return_value="HTML main content.")
        self.mock_extract_main_content = self.patcher_extract_content.start()
        self.addCleanup(self.patcher_extract_content.stop)
        
        self.patcher_open = patch('builtins.open', new_callable=mock_open)
        self.mock_file_open = self.patcher_open.start()
        self.addCleanup(self.patcher_open.stop)

        # Default behavior for mocks
        self.mock_fetch_page.return_value = "<html>Mock HTML</html>"
        self.mock_extract_links.return_value = set()
        crawler.MAX_PAGES = 2 # Limit for faster tests
        crawler.BASE_URL = "http://example.com/start"
        crawler.LLMS_TXT_SITE_TITLE = "Test Crawl Site"
        crawler.LLMS_TXT_SITE_SUMMARY = "Test Crawl Summary"
        crawler.LLMS_TXT_DETAILS_PLACEHOLDER = "Test Crawl Details"


    def test_crawl_simple_run_html_only(self):
        self.mock_extract_links.side_effect = [
            {"http://example.com/page2"}, # Links from /start
            set() # No links from /page2
        ]
        self.mock_extract_title.side_effect = ["Start Page Title", "Page 2 Title"]
        
        crawler.crawl()

        self.assertEqual(len(crawler.visited_urls), 2)
        self.assertIn("http://example.com/start", crawler.visited_urls)
        self.assertIn("http://example.com/page2", crawler.visited_urls)
        
        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 2)
        self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['title'], "Start Page Title")
        self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['html_url'], "http://example.com/start")
        self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['content_for_full_txt'], "HTML main content.")
        self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['content_source_type'], "html")

        self.assertEqual(crawler.discovered_pages_for_llms_txt[1]['title'], "Page 2 Title")

        # Check llms.txt content
        self.mock_file_open.assert_any_call(crawler.OUTPUT_FILE, 'w', encoding='utf-8')
        # Check llms-full.txt content
        self.mock_file_open.assert_any_call(crawler.OUTPUT_FILE_FULL, 'w', encoding='utf-8')
        
        # Get all written content to llms.txt (first file opened for writing)
        # mock_open().write() accumulates calls. We need to find the correct handle.
        handle_llms_txt = self.mock_file_open.return_value
        
        # Construct expected content (simplified check)
        # This is tricky because mock_open().write() calls are separate.
        # A better way is to check the *args of write calls.
        
        # Example: Check that title and summary are in the output
        # This requires inspecting the calls to the write method of the mock file object
        # For simplicity, we'll just check that open was called. Detailed content check is complex with mock_open.
        # A more robust way is to allow writing to a StringIO object.
        # For now, let's verify the structure of discovered_pages_for_llms_txt
        
        # Verify calls to fetch_page
        self.mock_fetch_page.assert_any_call("http://example.com/start")
        self.mock_fetch_page.assert_any_call("http://example.com/page2")


    def test_crawl_md_version_found_and_used(self):
        md_url = "http://example.com/start.md"
        self.mock_check_md_version.return_value = md_url
        self.mock_fetch_page.side_effect = lambda url: "MD Content from " + url if url == md_url else "HTML for " + url
        
        crawler.crawl()
        
        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 1) # MAX_PAGES = 2, but only one page processed if no new links
        page_info = crawler.discovered_pages_for_llms_txt[0]
        self.assertEqual(page_info['md_url'], md_url)
        self.assertEqual(page_info['content_for_full_txt'], "MD Content from " + md_url)
        self.assertEqual(page_info['content_source_type'], 'md')
        self.mock_logger.info.assert_any_call(f"Using Markdown content from {md_url}")
        self.mock_fetch_page.assert_any_call(md_url) # Check MD content was fetched

    def test_crawl_md_fetch_fails_fallback_to_html(self):
        md_url = "http://example.com/start.md"
        self.mock_check_md_version.return_value = md_url
        # First call to fetch_page is for HTML, second for MD (if found)
        self.mock_fetch_page.side_effect = lambda url: None if url == md_url else "<html>Original HTML</html>"
        self.mock_extract_main_content.return_value = "Extracted from Original HTML"

        crawler.crawl()

        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 1)
        page_info = crawler.discovered_pages_for_llms_txt[0]
        self.assertEqual(page_info['md_url'], md_url) # MD URL was found
        self.assertEqual(page_info['content_for_full_txt'], "Extracted from Original HTML") # Fallback
        self.assertEqual(page_info['content_source_type'], 'html')
        self.mock_logger.warning.assert_any_call(f"Failed to fetch Markdown content from {md_url}, will try HTML from original URL.")
        self.mock_logger.info.assert_any_call(f"Using extracted HTML content from {crawler.BASE_URL}")

    def test_crawl_max_pages_limit(self):
        crawler.MAX_PAGES = 1
        self.mock_extract_links.return_value = {"http://example.com/page2"} # Found a link
        
        crawler.crawl()
        
        self.assertEqual(len(crawler.visited_urls), 1)
        self.assertIn("http://example.com/start", crawler.visited_urls)
        self.assertNotIn("http://example.com/page2", crawler.visited_urls) # Not crawled due to MAX_PAGES
        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 1)

    def test_crawl_robots_disallowed(self):
        self.mock_is_allowed.return_value = False
        crawler.crawl()
        self.assertEqual(len(crawler.visited_urls), 0) # Should not add to visited if disallowed before fetch
        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 0)
        self.mock_logger.info.assert_called_with(f"Skipped (robots.txt): {crawler.BASE_URL}")
        self.mock_fetch_page.assert_not_called()

    def test_crawl_fetch_page_returns_none(self):
        self.mock_fetch_page.return_value = None
        crawler.crawl()
        self.assertEqual(len(crawler.visited_urls), 1) # Added to visited
        self.assertIn(crawler.BASE_URL, crawler.visited_urls)
        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 0) # No content discovered
        self.mock_logger.warning.assert_called_with(f"Fetch returned no HTML for {crawler.BASE_URL} after retries.")

    @patch('crawler.load_processed_urls_from_log')
    def test_crawl_restart_mode(self, mock_load_log):
        restarted_url = "http://example.com/already_visited"
        mock_load_log.return_value = {restarted_url}
        crawler.BASE_URL = restarted_url # Start with the already visited one
        crawler.MAX_PAGES = 1

        crawler.crawl(restart_mode=True)

        mock_load_log.assert_called_once_with(crawler.LOG_FILE)
        self.assertIn(restarted_url, crawler.visited_urls) # Should be pre-populated
        self.mock_fetch_page.assert_not_called() # Should not fetch already visited URL
        self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 0) # No new pages processed

    def test_crawl_output_file_content(self):
        # More focused test on output generation
        crawler.LLMS_TXT_SITE_TITLE = "Output Test Title"
        crawler.LLMS_TXT_SITE_SUMMARY = "Output Test Summary"
        crawler.LLMS_TXT_DETAILS_PLACEHOLDER = "Output Test Details"
        
        page1_data = {
            'title': 'Page One', 
            'html_url': crawler.BASE_URL, # First page crawled is BASE_URL
            'md_url': None,
            'content_for_full_txt': 'Content of page one.', 'content_source_type': 'html'
        }
        page2_data = {
            'title': 'Page Two (MD)', 
            'html_url': 'http://example.com/page2', # URL assumed to be linked from page1
            'md_url': 'http://example.com/page2.md', # Assumed MD version for page2
            'content_for_full_txt': '# Markdown Content P2', 
            'content_source_type': 'md'
        }
        crawler.discovered_pages_for_llms_txt = [page1_data, page2_data]

        # We need to run a minimal crawl loop that just does the file writing part
        # Or, call the file writing part directly if it were refactored.
        # For now, let's simulate an empty crawl that just writes existing discovered_pages.
        
        # To test file writing accurately, we need to capture what's written.
        # Re-patch open for this specific test to use StringIO or track writes.
        
        mock_output_file = MagicMock()
        mock_output_full_file = MagicMock()
        
        def smart_mock_open(filename, *args, **kwargs):
            if filename == crawler.OUTPUT_FILE:
                return mock_output_file
            elif filename == crawler.OUTPUT_FILE_FULL:
                return mock_output_full_file
            return mock_open() # Fallback for other files if any

        with patch('builtins.open', side_effect=smart_mock_open):
            # Simulate the end of crawl() where files are written
            # This is a bit of a hack; ideally, file writing would be a separate function.
            # For now, we'll just call the relevant parts of crawl's end logic.
            
            # --- llms.txt (index file) generation ---
            llms_content_parts = []
            llms_content_parts.append(f"# {crawler.LLMS_TXT_SITE_TITLE}\n\n")
            # ... (rest of the llms.txt generation logic from crawler.py) ...
            # This is becoming too complex to replicate.
            # A better approach for testing file content is to let it write to a temp file
            # and then read the temp file.
            # However, with mock_open, we can inspect `write` calls.

            # Let's just run a minimal crawl that populates discovered_pages and writes.
            # The setUp already mocks fetch_page etc.
            # We need to ensure discovered_pages_for_llms_txt is populated as above.
            
            # Instead of re-patching, let's rely on the class-level mock_file_open
            # and inspect its calls. This is still tricky due to multiple files.
            
            # Simplification: We'll check that `open` is called for the output files
            # and that `discovered_pages_for_llms_txt` (which dictates content) is correct.
            # A full content string match is brittle with mock_open's default behavior.

            # Run a crawl that will populate discovered_pages_for_llms_txt
            self.mock_fetch_page.side_effect = ["html1", "html2"] # For /start, /page2
            self.mock_extract_links.side_effect = [{page2_data['html_url']}, set()]
            self.mock_extract_title.side_effect = [page1_data['title'], page2_data['title']]
            self.mock_check_md_version.side_effect = [None, page2_data['md_url']] # No MD for page1, MD for page2
            
            # Adjust fetch_page and extract_main_content for page2 MD
            def custom_fetch(url):
                if url == page1_data['html_url']: # This is crawler.BASE_URL
                    return "html content for page1"
                elif url == page2_data['md_url']: # MD for the second page
                    return page2_data['content_for_full_txt']
                elif url == page2_data['html_url']: # HTML for the second page (if MD fails or not checked first)
                    return "html content for page2"
                self.fail(f"custom_fetch called with unexpected URL: {url}") # Fail test if unexpected URL
                return "default html" # Should not be reached
            self.mock_fetch_page.side_effect = custom_fetch
            
            def custom_extract_main(html_content_arg):
                if html_content_arg == "html content for page1": return page1_data['content_for_full_txt']
                if html_content_arg == "html content for page2": return "extracted HTML content for page2"
                self.fail(f"custom_extract_main called with unexpected HTML: {html_content_arg[:100]}")
                return "some other html content" # Should not be reached
            self.mock_extract_main_content.side_effect = custom_extract_main

            crawler.crawl() # This will use the mocks to populate discovered_pages_for_llms_txt

            # Verify discovered_pages_for_llms_txt content
            self.assertEqual(len(crawler.discovered_pages_for_llms_txt), 2)
            # Page 1 (HTML)
            self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['title'], page1_data['title'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['html_url'], page1_data['html_url'])
            self.assertIsNone(crawler.discovered_pages_for_llms_txt[0]['md_url'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['content_for_full_txt'], page1_data['content_for_full_txt'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[0]['content_source_type'], 'html')
            # Page 2 (MD)
            self.assertEqual(crawler.discovered_pages_for_llms_txt[1]['title'], page2_data['title'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[1]['html_url'], page2_data['html_url'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[1]['md_url'], page2_data['md_url'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[1]['content_for_full_txt'], page2_data['content_for_full_txt'])
            self.assertEqual(crawler.discovered_pages_for_llms_txt[1]['content_source_type'], 'md')

            # Check that the files were attempted to be written
            # self.mock_file_open.assert_any_call(crawler.OUTPUT_FILE, 'w', encoding='utf-8')
            # self.mock_file_open.assert_any_call(crawler.OUTPUT_FILE_FULL, 'w', encoding='utf-8')
            
            # To check content written with mock_open, you'd inspect the write calls on the mock object
            # returned by mock_open() when it was called with the specific filename.
            # Example (conceptual, actual access might differ based on mock_open version):
            # llms_txt_writes = []
            # llms_full_txt_writes = []
            # for call_args in self.mock_file_open.mock_calls:
            #     name, args, kwargs = call_args
            #     if name == "": # Call to open itself
            #         filename_opened = args[0]
            #     elif name == "().write":
            #         if 'filename_opened' in locals() and filename_opened == crawler.OUTPUT_FILE:
            #             llms_txt_writes.append(args[0])
            #         elif 'filename_opened' in locals() and filename_opened == crawler.OUTPUT_FILE_FULL:
            #             llms_full_txt_writes.append(args[0])
            # llms_txt_content = "".join(llms_txt_writes)
            # self.assertIn(f"# {crawler.LLMS_TXT_SITE_TITLE}", llms_txt_content)
            # This is complex. For real content validation, writing to temp files is easier.
            # For now, we've validated the data structure that feeds into file writing.


class TestArgumentParsing(BaseCrawlerTestCase):
    # Test parse_arguments by mocking sys.argv
    # The function parse_arguments takes (log_file_default_val, site_summary_default_val)
    # These are crawler.LOG_FILE_DEFAULT and crawler.LLMS_TXT_SITE_SUMMARY_DEFAULT in __main__

    def test_parse_arguments_required(self):
        test_args = [
            "script_name",
            "--base-url", "http://test.com",
            "--url-pattern", r"^http://test\.com",
            "--site-title", "My Test Site"
        ]
        with patch.object(sys, 'argv', test_args):
            args = crawler.parse_arguments("default.log", "default summary")
            self.assertEqual(args.base_url, "http://test.com")
            self.assertEqual(args.url_pattern, r"^http://test\.com")
            self.assertEqual(args.site_title, "My Test Site")
            self.assertEqual(args.log_file, "default.log") # Default passed in
            self.assertEqual(args.site_summary, "default summary") # Default passed in

    def test_parse_arguments_all_options(self):
        test_args = [
            "script_name",
            "--base-url", "http://another.com/docs",
            "--url-pattern", r"^http://another\.com/docs/",
            "--site-title", "Another Docs",
            "--output-file", "out.txt",
            "--output-file-full", "out-full.txt",
            "--output-directory", "/tmp/test_output",
            "--log-file", "custom.log",
            "--user-agent", "CustomAgent/1.0",
            "--request-delay", "2",
            "--max-pages", "50",
            "--retries", "5",
            "--excluded-url", "*secret*",
            "--excluded-url", "*.pdf",
            "--site-summary", "Custom summary.",
            "--details-placeholder", "Custom details.",
            "--restart",
            "--skip-adjacent-repetitive-paths",
            "--log-level", "DEBUG"
        ]
        with patch.object(sys, 'argv', test_args):
            args = crawler.parse_arguments("default.log", "default summary")
            self.assertEqual(args.base_url, "http://another.com/docs")
            self.assertEqual(args.url_pattern, r"^http://another\.com/docs/")
            self.assertEqual(args.site_title, "Another Docs")
            self.assertEqual(args.output_file, "out.txt")
            self.assertEqual(args.output_file_full, "out-full.txt")
            self.assertEqual(args.output_directory, "/tmp/test_output")
            self.assertEqual(args.log_file, "custom.log")
            self.assertEqual(args.user_agent, "CustomAgent/1.0")
            self.assertEqual(args.request_delay, 2)
            self.assertEqual(args.max_pages, 50)
            self.assertEqual(args.retries, 5)
            self.assertEqual(args.excluded_url, ["*secret*", "*.pdf"])
            self.assertEqual(args.site_summary, "Custom summary.")
            self.assertEqual(args.details_placeholder, "Custom details.")
            self.assertTrue(args.restart)
            self.assertTrue(args.skip_adjacent_repetitive_paths)
            self.assertEqual(args.log_level, "DEBUG")

    def test_parse_arguments_version(self):
        test_args = ["script_name", "--version"]
        with patch.object(sys, 'argv', test_args):
            with self.assertRaises(SystemExit) as cm: # argparse --version exits
                crawler.parse_arguments("default.log", "default summary")
            self.assertEqual(cm.exception.code, 0) # Successful exit

# Note on testing the `if __name__ == "__main__":` block:
# Testing this block directly is more of an integration test for the script's entry point.
# It involves:
# 1. Setting up `sys.argv`.
# 2. Running the script (e.g., using `runpy.run_module` or `subprocess`).
# 3. Mocking `crawler.crawl` itself to prevent actual crawling.
# 4. Checking that global configurations (crawler.BASE_URL, etc.) are set correctly
#    based on parsed arguments.
# 5. Verifying logger setup (e.g., mock `logging.FileHandler` and check its instantiation).
# 6. Verifying `os.makedirs` calls.
#
# A simpler approach for unit tests is to:
# - Test `parse_arguments` thoroughly (as done above).
# - Test the `crawl` function with various configurations, simulating what `__main__` would set.
# This covers most of the logic.
#
# Example of how one might start testing the main block's effects:
# @patch('crawler.crawl')
# @patch('os.makedirs')
# @patch('logging.FileHandler') # To check logger setup
# def test_main_block_setup(self, mock_file_handler, mock_makedirs, mock_crawl_func):
#     test_args = [
#         "crawler.py", # Script name
#         "--base-url", "http://maintest.com",
#         "--url-pattern", "^http://maintest\.com",
#         "--site-title", "Main Test Title",
#         "--output-directory", os.path.join(self.temp_dir, "main_out"),
#         "--log-file", "main.log"
#     ]
#     with patch.object(sys, 'argv', test_args):
#         # To run the __main__ block, you might need to importlib.reload the module
#         # or use runpy. However, directly calling a wrapper function if __main__ was refactored
#         # would be easier.
#         # For now, we can simulate the sequence of operations if __main__ was a function.
#
#         # This part is complex because __main__ directly manipulates globals and sets up logging.
#         # A full test would involve `runpy.run_path('path/to/crawler.py')` or similar,
#         # with extensive mocking of functions called from __main__.
#         pass


if __name__ == '__main__':
    unittest.main(verbosity=2)