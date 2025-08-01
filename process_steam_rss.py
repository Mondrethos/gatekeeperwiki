import requests
import xml.etree.ElementTree as ET
from datetime import datetime
import os
import sys
import json
import re
from pathlib import Path
import hashlib
from email.utils import parsedate_to_datetime

def sanitize_filename(title):
    """Convert title to valid filename"""
    # Remove special characters
    filename = re.sub(r'[<>:"/\\|?*]', '', title)
    # Replace spaces and multiple spaces with single hyphen
    filename = re.sub(r'\s+', '-', filename)
    # Remove multiple hyphens
    filename = re.sub(r'-+', '-', filename)
    # Remove non-ASCII characters
    filename = ''.join(c for c in filename if ord(c) < 128)
    # Trim and lowercase
    filename = filename.strip('-').lower()
    # Limit length
    return filename[:50] if filename else 'untitled'

def parse_date(date_str):
    """Parse RSS date format"""
    try:
        return parsedate_to_datetime(date_str)
    except:
        return datetime.now()

def extract_image_url(description):
    """Extract first image URL from description HTML"""
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description)
    if img_match:
        url = img_match.group(1)
        # Handle relative URLs
        if url.startswith('//'):
            url = 'https:' + url
        return url
    return None

def clean_description(description):
    """Clean HTML from description"""
    # Remove image tags
    description = re.sub(r'<img[^>]*>', '', description)
    # Convert <br> to newlines
    description = re.sub(r'<br\s*/?>', '\n', description)
    # Remove all other HTML tags
    description = re.sub(r'<[^>]+>', '', description)
    # Decode HTML entities
    description = description.replace('&amp;', '&')
    description = description.replace('&lt;', '<')
    description = description.replace('&gt;', '>')
    description = description.replace('&quot;', '"')
    description = description.replace('&#39;', "'")
    # Clean up whitespace
    description = re.sub(r'\n\s*\n', '\n\n', description)
    return description.strip()

def download_image(url, output_path):
    """Download image from URL"""
    try:
        response = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; GatekeeperWikiBot/1.0)'
        })
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Failed to download image from {url}: {e}")
        return False

def generate_markdown(entry, output_dir):
    """Generate markdown file for RSS entry"""
    title = entry.get('title', 'Untitled')
    link = entry.get('link', '')
    pub_date = entry.get('pubDate', '')
    description = entry.get('description', '')

    # Parse date
    date_obj = parse_date(pub_date)
    date_str = date_obj.strftime('%Y-%m-%d')

    # Create filename
    safe_title = sanitize_filename(title)
    filename = f"{date_str}-{safe_title}.md"
    filepath = os.path.join(output_dir, filename)

    # Extract image and clean description
    image_url = extract_image_url(description)
    clean_desc = clean_description(description)

    # Prepare image filename if image exists
    image_filename = None
    if image_url:
        image_filename = f"{safe_title}.png"
        image_path = os.path.join(output_dir, image_filename)
        if download_image(image_url, image_path):
            print(f"Downloaded image: {image_filename}")
        else:
            image_filename = None

    # Generate markdown content
    content = f"""---
title: {title}
date: {date_str}
enableToc: false
---

> [!patchnote] Patch Note
>
> # {title}
>"""

    if image_filename:
        content += f"\n> ![[{image_filename}]]"

    content += f"\n> **Published:** {date_obj.strftime('%B %d, %Y')}\n>"

    # Add description with proper formatting
    for line in clean_desc.split('\n'):
        if line.strip():
            content += f"\n> {line}"
        else:
            content += "\n>"

    if link:
        content += f"\n>\n> [View on Steam]({link})"

    content += f"\n\n--- [Edit on GitHub](https://github.com/Mondrethos/gatekeeperwiki/edit/main/content/PatchNotes/{filename})"

    return filepath, content, filename

def main():
    url = os.environ.get('STEAM_RSS_URL', sys.argv[1] if len(sys.argv) > 1 else '')
    output_dir = os.environ.get('CONTENT_DIR', 'content/PatchNotes')
    force_update = os.environ.get('FORCE_UPDATE', 'false').lower() == 'true'

    if not url:
        print("Error: No RSS URL provided")
        sys.exit(1)

    print(f"Processing RSS feed: {url}")
    print(f"Output directory: {output_dir}")
    print(f"Force update: {force_update}")

    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Load existing content hashes
    hash_file = 'content_hashes.json'
    existing_hashes = {}
    if os.path.exists(hash_file) and not force_update:
        try:
            with open(hash_file, 'r') as f:
                existing_hashes = json.load(f)
        except:
            pass

    results = {
        'new_entries': 0,
        'updated_entries': 0,
        'errors': [],
        'processed': []
    }

    try:
        # Fetch RSS feed
        print("Fetching RSS feed...")
        response = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; GatekeeperWikiBot/1.0)'
        })
        response.raise_for_status()

        # Parse XML
        print("Parsing RSS feed...")
        root = ET.fromstring(response.content)

        # Find all items
        items = root.findall('.//item')
        print(f"Found {len(items)} items in feed")

        if not items:
            print("Warning: No items found in RSS feed")
            # Try alternate structure
            items = root.findall('.//{http://purl.org/rss/1.0/}item')
            print(f"Trying alternate structure, found {len(items)} items")

        for i, item in enumerate(items):
            print(f"\nProcessing item {i+1}/{len(items)}")

            entry = {}
            for child in item:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                entry[tag] = child.text

            if not entry.get('title'):
                print("Skipping item without title")
                continue

            print(f"Title: {entry.get('title', 'N/A')}")

            # Generate content
            filepath, content, filename = generate_markdown(entry, output_dir)

            # Calculate content hash
            content_hash = hashlib.md5(content.encode()).hexdigest()

            # Check if content changed
            if filepath in existing_hashes and existing_hashes[filepath] == content_hash:
                print(f"Content unchanged, skipping: {filename}")
                continue

            # Write markdown file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"Written: {filename}")

            # Update tracking
            if filepath in existing_hashes:
                results['updated_entries'] += 1
            else:
                results['new_entries'] += 1

            existing_hashes[filepath] = content_hash
            results['processed'].append(filename)

        # Save updated hashes
        with open(hash_file, 'w') as f:
            json.dump(existing_hashes, f, indent=2)

    except Exception as e:
        error_msg = f"Feed processing error: {str(e)}"
        print(f"Error: {error_msg}")
        results['errors'].append(error_msg)

    # Save results
    with open('processing_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Print summary
    print(f"\n{'='*50}")
    print(f"Processing complete:")
    print(f"- New entries: {results['new_entries']}")
    print(f"- Updated entries: {results['updated_entries']}")
    print(f"- Total processed: {len(results['processed'])}")
    print(f"- Errors: {len(results['errors'])}")

    if results['processed']:
        print(f"\nProcessed files:")
        for file in results['processed']:
            print(f"  - {file}")

    # Set outputs for GitHub Actions
    print(f"\n::set-output name=new_entries::{results['new_entries']}")
    print(f"::set-output name=updated_entries::{results['updated_entries']}")
    print(f"::set-output name=has_changes::{len(results['processed']) > 0}")

    # Exit with error if processing failed completely
    if results['errors'] and not results['processed']:
        sys.exit(1)

if __name__ == '__main__':
    main()
