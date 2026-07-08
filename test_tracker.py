import unittest
from unittest.mock import patch, MagicMock
import tracker

class TestWebpageTracker(unittest.TestCase):

    def test_clean_text(self):
        """Test normalized whitespace cleaning."""
        raw_text = "  Hello \n\n   World!  \n\n\n  Good   morning. "
        expected = "Hello\n\nWorld!\n\nGood   morning."
        self.assertEqual(tracker.clean_text(raw_text), expected)

    @patch('requests.get')
    def test_fetch_page_content_basic(self, mock_get):
        """Test default page text extraction (no selectors)."""
        html_content = """
        <html>
            <head><title>Test Title</title></head>
            <body>
                <h1>Header Text</h1>
                <p>Paragraph Text.</p>
                <script>console.log('exclude me');</script>
                <style>body { color: red; }</style>
            </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        extracted = tracker.fetch_page_content("http://mockurl.com")
        self.assertIn("Header Text", extracted)
        self.assertIn("Paragraph Text.", extracted)
        self.assertNotIn("exclude me", extracted)
        self.assertNotIn("color: red", extracted)

    @patch('requests.get')
    def test_fetch_page_content_include_selector(self, mock_get):
        """Test filtering with include (whitelist) selectors."""
        html_content = """
        <html>
            <body>
                <div class="content">Target content block</div>
                <div class="sidebar">Ignore sidebar content</div>
            </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        # Test whitelist filter
        extracted = tracker.fetch_page_content(
            "http://mockurl.com", 
            include_selectors=".content"
        )
        self.assertEqual(extracted, "Target content block")
        self.assertNotIn("Ignore sidebar content", extracted)

    @patch('requests.get')
    def test_fetch_page_content_ignore_selector(self, mock_get):
        """Test filtering with ignore (blacklist) selectors."""
        html_content = """
        <html>
            <body>
                <div class="main">
                    <h1>Main Heading</h1>
                    <div class="timestamp">Checked on 2026-07-04</div>
                    <p>Core content details.</p>
                </div>
            </body>
        </html>
        """
        mock_response = MagicMock()
        mock_response.text = html_content
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        # Test blacklist filter (remove timestamp)
        extracted = tracker.fetch_page_content(
            "http://mockurl.com", 
            ignore_selectors=".timestamp"
        )
        self.assertIn("Main Heading", extracted)
        self.assertIn("Core content details.", extracted)
        self.assertNotIn("2026-07-04", extracted)

    def test_check_sensitivity_always(self):
        """Test that 'always' sensitivity preset triggers on any minor change."""
        old_text = "Standard paragraph content."
        new_text = "Standard paragraph contents." # 1 character added
        
        is_changed, ratio = tracker.check_sensitivity(old_text, new_text, 'always')
        self.assertTrue(is_changed)
        self.assertLess(ratio, 1.0)

    def test_check_sensitivity_low(self):
        """Test that 'low' sensitivity preset ignores minor differences."""
        # Create a large text where a small edit results in a similarity ratio > 0.95
        old_text = "This is a very long paragraph. " * 20  # 600 chars
        new_text = old_text + " Edit."                     # 606 chars (similarity ratio ~ 0.995)
        
        # Low sensitivity (threshold 0.95)
        is_changed, ratio = tracker.check_sensitivity(old_text, new_text, 'low')
        # Similarity ratio is ~0.995, which is >= 0.95, so change is IGNORED (is_changed = False)
        self.assertFalse(is_changed)
        self.assertGreater(ratio, 0.95)

        # Medium sensitivity (threshold 0.99)
        is_changed_med, ratio_med = tracker.check_sensitivity(old_text, new_text, 'medium')
        # Similarity ratio ~0.995 is >= 0.99, so it should also be ignored
        self.assertFalse(is_changed_med)

        # High sensitivity (threshold 0.999)
        is_changed_high, ratio_high = tracker.check_sensitivity(old_text, new_text, 'high')
        # Similarity ratio ~0.995 is < 0.999, so it SHOULD be caught
        self.assertTrue(is_changed_high)


if __name__ == '__main__':
    unittest.main()
