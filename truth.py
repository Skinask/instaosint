"""
Instagram Public Profile Analyzer (Authenticated & Rate-Limit Resilient)
------------------------------------------------------------------------
Includes built-in Instagram login support to bypass aggressive 429 limits
and save session cookies locally.
"""

import csv
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import instaloader
from instaloader.exceptions import ConnectionException


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

OUTPUT_DIR = Path("instagram_results")

# Maximum number of posts to process.
DEFAULT_MAX_POSTS = 20

# Maximum comments to collect per post.
DEFAULT_MAX_COMMENTS = 50

# Base delay between requests (seconds).
REQUEST_DELAY = 3

# Maximum retries for rate-limited requests
MAX_RETRIES = 3


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean_text(value):
    """Make text safe for CSV/JSON output."""
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()


def safe_filename(username):
    """Create a safe filename."""
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    result = "".join(char if char in allowed else "_" for char in username)
    return result or "instagram_user"


def make_loader():
    """Create an Instaloader instance and handle authentication."""
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        save_metadata=False,
        compress_json=False,
    )
    
    print("\n" + "=" * 60)
    print(" INSTAGRAM AUTHENTICATION")
    print("=" * 60)
    print("Note: Instagram requires an account login to bypass HTTP 429 limits.")
    print("Use a burner account, never your main account.\n")
    
    # Check for existing session files in the current directory
    session_files = list(Path(".").glob("session-*"))
    if session_files:
        session_file = session_files[0]
        account_name = session_file.name.replace("session-", "")
        use_existing = input(f"Found saved session for '@{account_name}'. Use it? [Y/n]: ").strip().lower()
        if use_existing != 'n':
            try:
                loader.load_session_from_file(account_name)
                print(f"[*] Successfully loaded session for @{account_name}")
                return loader
            except Exception as exc:
                print(f"[!] Failed to load session file: {exc}")

    # Prompt for credentials if no session exists or user chose to re-login
    ig_user = input("Enter Instagram username (burner): ").strip().lstrip("@")
    if ig_user:
        ig_pass = input("Enter Instagram password: ").strip()
        try:
            print(f"[*] Logging in as @{ig_user}...")
            loader.login(ig_user, ig_pass)
            loader.save_session_to_file(ig_user)
            print(f"[*] Login successful! Session cached for future runs.")
        except Exception as exc:
            print(f"[!] Login failed: {exc}")
            print("[!] Proceeding unauthenticated (expect high risk of 429 errors).")
            
    return loader


def smart_sleep():
    """Sleep for a randomized duration to mimic human behavior."""
    sleep_time = REQUEST_DELAY + random.uniform(1.0, 3.0)
    time.sleep(sleep_time)


# ---------------------------------------------------------
# Profile
# ---------------------------------------------------------

def get_profile(loader, username):
    """Find a public Instagram profile with retry logic for rate limits."""
    username = username.strip().lstrip("@")
    if not username:
        raise ValueError("Username cannot be empty.")

    retries = 0
    while retries <= MAX_RETRIES:
        try:
            profile = instaloader.Profile.from_username(loader.context, username)
            return profile
        except ConnectionException as exc:
            if "429" in str(exc) or "Too Many Requests" in str(exc):
                retries += 1
                backoff = (2 ** retries) * 30
                print(f"\n[!] Rate-limited (429). Backing off for {backoff} seconds (Attempt {retries}/{MAX_RETRIES})...")
                time.sleep(backoff)
            else:
                raise RuntimeError(f"Connection error accessing @{username}: {exc}")
        except Exception as exc:
            raise RuntimeError(f"Could not access @{username}: {exc}")
            
    raise RuntimeError(f"Max retries reached. IP or session is heavily rate-limited.")


def profile_to_dict(profile):
    """Convert profile information to a dictionary."""
    return {
        "username": clean_text(profile.username),
        "full_name": clean_text(profile.full_name),
        "biography": clean_text(profile.biography),
        "followers": profile.followers,
        "following": profile.followees,
        "posts": profile.mediacount,
        "is_private": profile.is_private,
        "is_verified": profile.is_verified,
        "external_url": clean_text(profile.external_url),
        "profile_url": f"https://www.instagram.com/{profile.username}/",
    }


# ---------------------------------------------------------
# Comments
# ---------------------------------------------------------

def collect_comments(post, max_comments):
    """Collect comments that are publicly accessible."""
    comments = []
    if max_comments <= 0:
        return comments

    try:
        for index, comment in enumerate(post.get_comments()):
            if index >= max_comments:
                break

            comments.append({
                "username": clean_text(comment.owner.username),
                "text": clean_text(comment.text),
                "date": comment.created_at_utc.isoformat() if comment.created_at_utc else "",
            })
            time.sleep(0.4)

    except Exception as exc:
        print(f"    [!] Comments unavailable or restricted: {exc}")

    return comments


# ---------------------------------------------------------
# Posts
# ---------------------------------------------------------

def collect_posts(profile, max_posts, max_comments):
    """Collect publicly accessible posts/reels."""
    posts = []

    if profile.is_private:
        print("\n[!] This profile is private.")
        return posts

    print("\nCollecting posts...\n")

    try:
        post_iterator = profile.get_posts()
        index = 0

        while index < max_posts:
            try:
                post = next(post_iterator, None)
                if not post:
                    break
                
                print(f"[{index + 1}/{max_posts}] {post.shortcode}")

                if post.is_video:
                    media_type = "video"
                elif post.typename == "GraphSidecar":
                    media_type = "carousel"
                else:
                    media_type = "photo"

                comments = collect_comments(post, max_comments)

                post_data = {
                    "shortcode": clean_text(post.shortcode),
                    "url": f"https://www.instagram.com/p/{post.shortcode}/",
                    "media_type": media_type,
                    "date": post.date_utc.isoformat() if post.date_utc else "",
                    "caption": clean_text(post.caption),
                    "likes": post.likes,
                    "comments_count": post.comments,
                    "is_video": post.is_video,
                    "video_view_count": post.video_view_count if post.is_video else None,
                    "owner": clean_text(post.owner_username),
                    "comments": comments,
                }

                posts.append(post_data)
                index += 1
                smart_sleep()

            except ConnectionException as exc:
                if "429" in str(exc) or "Too Many Requests" in str(exc):
                    print(f"\n[!] Rate-limited mid-collection. Pausing for 60 seconds...")
                    time.sleep(60)
                    continue
                else:
                    print(f"\n[!] Connection exception: {exc}")
                    break

    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")
    except Exception as exc:
        print(f"\n[!] Error while collecting posts: {exc}")

    return posts


# ---------------------------------------------------------
# Export JSON & CSV
# ---------------------------------------------------------

def save_json(username, profile_data, posts):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = OUTPUT_DIR / f"{safe_filename(username)}.json"
    result = {
        "scraped_at": datetime.utcnow().isoformat(),
        "profile": profile_data,
        "posts": posts,
    }
    with filename.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=4, ensure_ascii=False)
    return filename


def save_posts_csv(username, posts):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = OUTPUT_DIR / f"{safe_filename(username)}_posts.csv"
    fields = ["shortcode", "url", "media_type", "date", "caption", "likes", "comments_count", "is_video", "video_view_count", "owner"]
    with filename.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for post in posts:
            writer.writerow({field: post.get(field, "") for field in fields})
    return filename


def save_comments_csv(username, posts):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = OUTPUT_DIR / f"{safe_filename(username)}_comments.csv"
    fields = ["post_shortcode", "post_url", "comment_username", "comment_date", "comment_text"]
    with filename.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for post in posts:
            for comment in post.get("comments", []):
                writer.writerow({
                    "post_shortcode": post["shortcode"],
                    "post_url": post["url"],
                    "comment_username": comment["username"],
                    "comment_date": comment["date"],
                    "comment_text": comment["text"],
                })
    return filename


# ---------------------------------------------------------
# Display
# ---------------------------------------------------------

def display_profile(profile_data):
    print("\n" + "=" * 60)
    print("PROFILE")
    print("=" * 60)
    print(f"Username     : @{profile_data['username']}")
    print(f"Name         : {profile_data['full_name']}")
    print(f"Followers    : {profile_data['followers']:,}")
    print(f"Following    : {profile_data['following']:,}")
    print(f"Posts        : {profile_data['posts']:,}")
    print(f"Private      : {profile_data['is_private']}")
    print(f"Verified     : {profile_data['is_verified']}")
    print(f"Website      : {profile_data['external_url']}")
    print(f"Profile URL  : {profile_data['profile_url']}")
    print(f"\nBio:\n{profile_data['biography']}")
    print("=" * 60)


def display_posts(posts):
    print("\n" + "=" * 60)
    print("POSTS")
    print("=" * 60)
    for index, post in enumerate(posts, 1):
        print(f"\n--- Post {index} ---")
        print(f"Type       : {post['media_type']}")
        print(f"Date       : {post['date']}")
        print(f"Likes      : {post['likes']}")
        print(f"Comments   : {post['comments_count']}")
        if post["is_video"]:
            print(f"Video views: {post['video_view_count']}")
        print(f"URL        : {post['url']}")
        if post["caption"]:
            print(f"Caption    : {post['caption'][:300]}")


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    print("=" * 60)
    print(" INSTAGRAM PUBLIC PROFILE ANALYZER (AUTHENTICATED)")
    print("=" * 60)

    loader = make_loader()

    username = input("\nTarget Instagram username to search: ").strip()
    if not username:
        print("Username required.")
        return

    max_posts_input = input(f"Maximum posts to collect (default {DEFAULT_MAX_POSTS}): ").strip()
    max_posts = int(max_posts_input) if max_posts_input.isdigit() else DEFAULT_MAX_POSTS

    comments_input = input(f"Maximum comments per post (default {DEFAULT_MAX_COMMENTS}): ").strip()
    max_comments = int(comments_input) if comments_input.isdigit() else DEFAULT_MAX_COMMENTS

    print(f"\nSearching for @{username.lstrip('@')}...")
    try:
        profile = get_profile(loader, username)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        return

    profile_data = profile_to_dict(profile)
    display_profile(profile_data)

    posts = collect_posts(profile, max_posts, max_comments)
    if posts:
        display_posts(posts)

    print("\nSaving results...")
    json_file = save_json(profile.username, profile_data, posts)
    posts_csv = save_posts_csv(profile.username, posts)
    comments_csv = save_comments_csv(profile.username, posts)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"\nProfile: @{profile.username}")
    print(f"Posts collected: {len(posts)}")
    print(f"\nJSON file:\n  {json_file}")
    print(f"\nPosts CSV:\n  {posts_csv}")
    print(f"\nComments CSV:\n  {comments_csv}")
    print("\nFiles are saved in the 'instagram_results' folder.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nStopped.")
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        sys.exit(1)
