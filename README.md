# 📜 [Doc Crawler](https://github.com/PieBru/doc_crawler)

Documentattion web sites crawler, as per https://llmstxt.org specifications.
License: Apache 2.0

## Introduction

Large language models increasingly rely on website information, but face a critical limitation: context windows are too small to handle most websites in their entirety. Converting complex HTML pages with navigation, ads, and JavaScript into LLM-friendly plain text is both difficult and imprecise.

While websites serve both human readers and LLMs, the latter benefit from more concise, expert-level information gathered in a single, accessible location. This is particularly important for use cases like development environments, where LLMs need quick access to programming documentation and  APIs.

The "llms.txt" specification is a proposed standard for a text file placed on websites to help large language models (LLMs) navigate and understand structured content more effectively. It defines files like /llms.txt for a concise overview of site navigation and /llms-full.txt for detailed content, aiming to provide AI systems with curated paths to resources such as API documentation or product taxonomies.

## Purpose

This specification addresses challenges in AI content processing by offering a structured format that LLMs can parse to extract relevant information without needing to crawl the entire site.

## Usage
    ```
    ❯ python crawler.py --help
    usage: crawler.py [-h] [--version] [--log-level {NONE,DEBUG,INFO,WARNING,ERROR,CRITICAL}] --base-url BASE_URL --url-pattern URL_PATTERN
                    [--output-file OUTPUT_FILE] [--output-file-full OUTPUT_FILE_FULL] [--output-type {txt,md,json,xml}] [--log-file LOG_FILE]
                    [--user-agent USER_AGENT] [--request-delay REQUEST_DELAY] [--max-pages MAX_PAGES] [--retries RETRIES] [--excluded-url EXCLUDED_URL]
                    --site-title SITE_TITLE [--site-summary SITE_SUMMARY] [--details-placeholder DETAILS_PLACEHOLDER] [--restart]
                    [--skip-adjacent-repetitive-paths]

    Crawl a documentation website to produce an llms.txt file.

    options:
    -h, --help            show this help message and exit
    --version             show program's version number and exit
    --log-level {NONE,DEBUG,INFO,WARNING,ERROR,CRITICAL}
                            Set the logging level. (Currently only prints the selection)
    --base-url BASE_URL   The root URL of the documentation to crawl (e.g., https://example.com/docs).
    --url-pattern URL_PATTERN
                            Regex pattern (as a string) to match documentation URLs (e.g., \"^https?://example\.com/docs/\").
    --output-file OUTPUT_FILE
                            Name for the llms.txt index file.
    --output-file-full OUTPUT_FILE_FULL
                            Name for the llms-full.txt content file.
    --output-type {txt,md,json,xml}
                            Desired output type. Affects default file extensions if --output-file/--output-file-full are not set. (Content generation for json/xml not yet implemented)
    --log-file LOG_FILE   Name for the log file.
    --user-agent USER_AGENT
                            User-Agent string for crawling.
    --request-delay REQUEST_DELAY
                            Delay in seconds between requests.
    --max-pages MAX_PAGES
                            Maximum number of pages to crawl.
    --retries RETRIES     Number of retries for fetching a page in case of an error.
    --excluded-url EXCLUDED_URL
                            URL pattern (supports wildcards like *) to exclude from crawling. Can be specified multiple times to exclude several patterns (e.g., --excluded-url "*/api/*" --excluded-url "*.pdf").
    --site-title SITE_TITLE
                            Site title for the H1 in generated files (e.g., "My Project Documentation").
    --site-summary SITE_SUMMARY
                            Site summary for the blockquote in llms.txt.
    --details-placeholder DETAILS_PLACEHOLDER
                            Text for the 'Optional details' section in llms.txt. If not set, this section will be empty.
    --restart             Restart a previous crawl, skipping pages logged as 'Successfully fetched' in the existing log file.
    --skip-adjacent-repetitive-paths
                            Skip URLs with more than two adjacent identical path segments (e.g., /word/word/word/). Default: False

    \
        Example usage:
        Crawl llmstxt.org (default configuration if these match):
            crawler.py --base-url "https://llmstxt.org/" \\
                    --url-pattern "^https?://llmstxt\.org/" \
                    --site-title "LLMs.txt Project"

        Crawl a different site:
            crawler.py --base-url "https://docs.example.com/" \\
                    --url-pattern "^https?://docs\.example\.com/" \
                    --site-title "Example Docs" --output-file "example_llms.txt"
    ```

### Examples

1.  **Crawl `llmstxt.org` (using script defaults for some parameters if they match):**
    ```bash
    python crawler.py \
        --base-url "https://llmstxt.org/" \
        --url-pattern "^https?://llmstxt\.org/" \
        --site-title "LLMs.txt Project Website" \
        --site-summary "Official documentation and resources for the llms.txt specification."
    ```
    This will produce `llms.txt` and `llms-full.txt`.

2.  **Crawl a different documentation site and specify output file names:**
    ```bash
    python crawler.py \
        --base-url "https://docs.yourproject.com/v1/" \
        --url-pattern "^https?://docs\.yourproject\.com/v1/" \
        --site-title "Your Project v1 Docs" \
        --site-summary "Comprehensive documentation for Your Project version 1." \
        --output-file "yourproject_index.md" \
        --output-file-full "yourproject_full_content.md" \
        --output-type md \
        --max-pages 500
    ```

## Testing and Coverage

This project uses Python's built-in `unittest` framework for unit tests and the `coverage` package for measuring test coverage.

### Running Unit Tests

1.  Navigate to the project root directory.
2.  If you are using a virtual environment, ensure it is activated.
3.  Run the tests using the following command:

    ```bash
    python -m unittest tests.test_crawler
    ```

### Checking Test Coverage

1.  **Install `coverage`** (if you haven't already):
    ```bash
    pip install coverage
    ```
2.  **Run tests with coverage**:
    ```bash
    coverage run -m unittest tests.test_crawler
    ```
3.  **View the coverage report**:
    *   For a quick summary in the console, including missing lines:
        ```bash
        coverage report -m
        ```
    *   For a detailed HTML report (generates an `htmlcov` directory):
        ```bash
        coverage html
        ```
        Open `htmlcov/index.html` in your browser to explore the interactive report.

## Output Files

*   **`llms.txt` (or as specified by `--output-file`)**:
*   
    An index file in Markdown format. Contains the site title, summary, optional details, and a list of links to discovered pages.

    ```markdown
    # [Site Title]

    > [Site Summary]

    [Optional Details Placeholder Text]

    ## Discovered Pages

    - [[Page Title 1]]([url1]): Source (Markdown version link / HTML page link)
    - [[Page Title 2]]([url2]): Source (Markdown version link / HTML page link)
    ...
    ```

*   **`llms-full.txt` (or as specified by `--output-file-full`)**:
*   A comprehensive Markdown file containing the full content of discovered pages.
    More details here: [What is "llms-full.txt" ?](README_what_is_llms-full.md)
    ```markdown
    # [Site Title]

    > [Site Summary]

    [Optional Details Placeholder Text]

    ## Discovered Pages Content

    - [[Page Title 1]]([url1]): Source (Content from Markdown source / Content extracted from HTML)

    [Full content of Page 1...]

    - [[Page Title 2]]([url2]): Source (Content from Markdown source / Content extracted from HTML)

    [Full content of Page 2...]
    ...
    ```

## Customization Tips

*   **Content Selectors**: The script uses `readability-lxml` for generic content extraction from HTML. If this is not effective for a specific site, you might need to customize `extract_main_content()` in `crawler.py` with site-specific BeautifulSoup selectors.
*   **URL Patterns**: Adjust the `--url-pattern` argument carefully to match your target documentation structure precisely.
*   **Dynamic Sites**: For JavaScript-heavy sites where content is rendered client-side, this crawler (which uses `requests`) might not capture all content. Consider using tools like Selenium or Playwright to fetch HTML in such cases and then feed it to a modified version of this script or a similar parser.
*   **`llms.txt` Details**: After generation, manually edit the `llms.txt` and `llms-full.txt` files to refine the "Optional details" section, organize links under more specific H2 headers, or add more descriptive notes to links.

## Contributing

Contributions are welcome! Please feel free to fork the repository, make changes, and submit a pull request.

## License

This project is licensed under the Apache License 2.0. See the `LICENSE` file for details.