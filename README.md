# 📜 [Doc Crawler](https://github.com/PieBru/doc_crawler)

Documentattion web sites crawler, as per https://llmstxt.org specifications.
License: Apache 2.0

Large language models increasingly rely on website information, 
but face a critical limitation: context windows are too small to handle
most websites in their entirety. Converting complex HTML pages with navigation, 
ads, and JavaScript into LLM-friendly plain text is both difficult and imprecise.

While websites serve both human readers and LLMs, the latter benefit from more 
concise, expert-level information gathered in a single, accessible location. 
This is particularly important for use cases like development environments, 
where LLMs need quick access to programming documentation and APIs.

The "llms.txt" specification is a proposed standard for a text file placed on 
websites to help large language models (LLMs) navigate and understand structured 
content more effectively. It defines files like /llms.txt for a concise overview 
of site navigation and /llms-full.txt for detailed content, aiming to provide AI 
systems with curated paths to resources such as API documentation or product taxonomies.
This specification addresses challenges in AI content processing by offering a 
structured format that LLMs can parse to extract relevant information without needing 
to crawl the entire site.

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
    More details here: [What the heck is "llms-full.txt" ?](README_wth_is_llms-full.md)
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

This project is licensed under the Apache License 2.0. See the `LICENSE` file for details (if one exists in your project).
