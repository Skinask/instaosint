"""
Instagram Public Profile Analyzer
----------------------------------

Collects publicly accessible profile/post information using Instaloader.

Features:
- Search a target username
- Display public profile information
- Collect public posts/reels
- Collect publicly accessible comments when available
- Export results to JSON and CSV
- No password required for public profiles

IMPORTANT:
Instagram's availability of data can change. This program does not:
- bypass private accounts
- bypass CAPTCHAs
- bypass rate limits
- attempt to identify hidden/alternate accounts
- access information that Instagram does not make publicly available

Install:
    pip install instaloader

Run:
    python instagram_analyzer.py

"""

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import instaloader


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

OUTPUT_DIR = Path("instagram_results")

# Maximum number of posts to process.
DEFAULT_MAX_POSTS = 20

# Maximum comments to collect per post.
# Set to 0 if you don't want comments.
DEFAULT_MAX_COMMENTS = 50

# Small delay between requests.
REQUEST_DELAY = 2


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

    result = "".join(
        char if char in allowed else "_"
        for char in username
    )

    return result or "instagram_user"


def make_loader():
    """Create an Instaloader instance."""

    return instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        save_metadata=False,
        compress_json=False,
    )


# ---------------------------------------------------------
# Profile
# ---------------------------------------------------------

def get_profile(loader, username):
    """Find a public Instagram profile."""

    username = username.strip().lstrip("@")

    if not username:
        raise ValueError("Username cannot be empty.")

    try:
        profile = instaloader.Profile.from_username(
            loader.context,
            username
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not access @{username}: {exc}"
        )

    return profile


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
    """
    Collect comments that are publicly accessible.

    This does not bypass Instagram restrictions.
    """

    comments = []

    if max_comments <= 0:
        return comments

    try:
        for index, comment in enumerate(post.get_comments()):

            if index >= max_comments:
                break

            comments.append({
                "username": clean_text(
                    comment.owner.username
                ),
                "text": clean_text(comment.text),
                "date": (
                    comment.created_at_utc.isoformat()
                    if comment.created_at_utc
                    else ""
                ),
            })

    except Exception as exc:
        print(
            f"    [!] Comments unavailable: {exc}"
        )

    return comments


# ---------------------------------------------------------
# Posts
# ---------------------------------------------------------

def collect_posts(
    profile,
    max_posts,
    max_comments
):
    """Collect publicly accessible posts/reels."""

    posts = []

    if profile.is_private:
        print("\n[!] This profile is private.")
        print(
            "Only information that Instagram exposes "
            "publicly can be collected."
        )
        return posts

    print("\nCollecting posts...\n")

    try:
        post_iterator = profile.get_posts()

        for index, post in enumerate(post_iterator):

            if index >= max_posts:
                break

            print(
                f"[{index + 1}/{max_posts}] "
                f"{post.shortcode}"
            )

            # Determine media type.
            if post.is_video:
                media_type = "video"
            elif post.typename == "GraphSidecar":
                media_type = "carousel"
            else:
                media_type = "photo"

            comments = collect_comments(
                post,
                max_comments
            )

            post_data = {
                "shortcode": clean_text(
                    post.shortcode
                ),

                "url": (
                    f"https://www.instagram.com/p/"
                    f"{post.shortcode}/"
                ),

                "media_type": media_type,

                "date": (
                    post.date_utc.isoformat()
                    if post.date_utc
                    else ""
                ),

                "caption": clean_text(
                    post.caption
                ),

                "likes": post.likes,

                "comments_count": post.comments,

                "is_video": post.is_video,

                "video_view_count": (
                    post.video_view_count
                    if post.is_video
                    else None
                ),

                "owner": clean_text(
                    post.owner_username
                ),

                "comments": comments,
            }

            posts.append(post_data)

            time.sleep(REQUEST_DELAY)

    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")

    except Exception as exc:
        print(
            f"\n[!] Error while collecting posts: {exc}"
        )

    return posts


# ---------------------------------------------------------
# Export JSON
# ---------------------------------------------------------

def save_json(username, profile_data, posts):
    """Save complete data to JSON."""

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    filename = (
        OUTPUT_DIR /
        f"{safe_filename(username)}.json"
    )

    result = {
        "scraped_at": datetime.utcnow().isoformat(),
        "profile": profile_data,
        "posts": posts,
    }

    with filename.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=4,
            ensure_ascii=False
        )

    return filename


# ---------------------------------------------------------
# Export CSV
# ---------------------------------------------------------

def save_posts_csv(username, posts):
    """Save post information to CSV."""

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    filename = (
        OUTPUT_DIR /
        f"{safe_filename(username)}_posts.csv"
    )

    fields = [
        "shortcode",
        "url",
        "media_type",
        "date",
        "caption",
        "likes",
        "comments_count",
        "is_video",
        "video_view_count",
        "owner",
    ]

    with filename.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()

        for post in posts:

            row = {
                field: post.get(field, "")
                for field in fields
            }

            writer.writerow(row)

    return filename


# ---------------------------------------------------------
# Export Comments
# ---------------------------------------------------------

def save_comments_csv(username, posts):
    """Save publicly accessible comments to CSV."""

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    filename = (
        OUTPUT_DIR /
        f"{safe_filename(username)}_comments.csv"
    )

    fields = [
        "post_shortcode",
        "post_url",
        "comment_username",
        "comment_date",
        "comment_text",
    ]

    with filename.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()

        for post in posts:

            for comment in post.get(
                "comments",
                []
            ):

                writer.writerow({
                    "post_shortcode": post[
                        "shortcode"
                    ],

                    "post_url": post[
                        "url"
                    ],

                    "comment_username": comment[
                        "username"
                    ],

                    "comment_date": comment[
                        "date"
                    ],

                    "comment_text": comment[
                        "text"
                    ],
                })

    return filename


# ---------------------------------------------------------
# Display
# ---------------------------------------------------------

def display_profile(profile_data):
    """Display profile information."""

    print("\n")
    print("=" * 60)
    print("PROFILE")
    print("=" * 60)

    print(
        f"Username     : "
        f"@{profile_data['username']}"
    )

    print(
        f"Name         : "
        f"{profile_data['full_name']}"
    )

    print(
        f"Followers    : "
        f"{profile_data['followers']:,}"
    )

    print(
        f"Following    : "
        f"{profile_data['following']:,}"
    )

    print(
        f"Posts        : "
        f"{profile_data['posts']:,}"
    )

    print(
        f"Private      : "
        f"{profile_data['is_private']}"
    )

    print(
        f"Verified     : "
        f"{profile_data['is_verified']}"
    )

    print(
        f"Website      : "
        f"{profile_data['external_url']}"
    )

    print(
        f"Profile URL  : "
        f"{profile_data['profile_url']}"
    )

    print(
        f"\nBio:\n"
        f"{profile_data['biography']}"
    )

    print("=" * 60)


def display_posts(posts):
    """Display collected posts."""

    print("\n")
    print("=" * 60)
    print("POSTS")
    print("=" * 60)

    for index, post in enumerate(posts, 1):

        print(f"\n--- Post {index} ---")

        print(
            f"Type       : "
            f"{post['media_type']}"
        )

        print(
            f"Date       : "
            f"{post['date']}"
        )

        print(
            f"Likes      : "
            f"{post['likes']}"
        )

        print(
            f"Comments   : "
            f"{post['comments_count']}"
        )

        if post["is_video"]:
            print(
                f"Video views: "
                f"{post['video_view_count']}"
            )

        print(
            f"URL        : "
            f"{post['url']}"
        )

        caption = post["caption"]

        if caption:
            print(
                f"Caption    : "
                f"{caption[:300]}"
            )

        comments = post.get(
            "comments",
            []
        )

        if comments:

            print(
                f"Public comments collected: "
                f"{len(comments)}"
            )

            for comment in comments[:5]:

                print(
                    f"  @{comment['username']}: "
                    f"{comment['text'][:100]}"
                )


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    print("=" * 60)
    print(" INSTAGRAM PUBLIC PROFILE ANALYZER")
    print("=" * 60)

    username = input(
        "\nTarget Instagram username: "
    ).strip()

    if not username:
        print("Username required.")
        return

    max_posts_input = input(
        "Maximum posts to collect "
        f"(default {DEFAULT_MAX_POSTS}): "
    ).strip()

    if max_posts_input:
        try:
            max_posts = int(
                max_posts_input
            )
        except ValueError:
            print(
                "Invalid number. "
                "Using default."
            )
            max_posts = DEFAULT_MAX_POSTS
    else:
        max_posts = DEFAULT_MAX_POSTS

    comments_input = input(
        "Maximum comments per post "
        f"(default {DEFAULT_MAX_COMMENTS}): "
    ).strip()

    if comments_input:
        try:
            max_comments = int(
                comments_input
            )
        except ValueError:
            print(
                "Invalid number. "
                "Using default."
            )
            max_comments = DEFAULT_MAX_COMMENTS
    else:
        max_comments = DEFAULT_MAX_COMMENTS

    if max_posts < 0:
        max_posts = 0

    if max_comments < 0:
        max_comments = 0

    loader = make_loader()

    # -----------------------------------------------------
    # Find profile
    # -----------------------------------------------------

    print(
        f"\nSearching for @{username.lstrip('@')}..."
    )

    try:
        profile = get_profile(
            loader,
            username
        )

    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        return

    # -----------------------------------------------------
    # Profile information
    # -----------------------------------------------------

    profile_data = profile_to_dict(
        profile
    )

    display_profile(
        profile_data
    )

    # -----------------------------------------------------
    # Posts
    # -----------------------------------------------------

    posts = collect_posts(
        profile,
        max_posts,
        max_comments
    )

    display_posts(posts)

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    print("\nSaving results...")

    json_file = save_json(
        profile.username,
        profile_data,
        posts
    )

    posts_csv = save_posts_csv(
        profile.username,
        posts
    )

    comments_csv = save_comments_csv(
        profile.username,
        posts
    )

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)

    print(
        f"\nProfile: "
        f"@{profile.username}"
    )

    print(
        f"Posts collected: "
        f"{len(posts)}"
    )

    print(
        f"\nJSON file:"
        f"\n  {json_file}"
    )

    print(
        f"\nPosts CSV:"
        f"\n  {posts_csv}"
    )

    print(
        f"\nComments CSV:"
        f"\n  {comments_csv}"
    )

    print(
        "\nThe files are saved in the "
        "'instagram_results' folder."
    )


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print("\n\nStopped.")

    except Exception as exc:
        print(
            f"\nUnexpected error: {exc}"
        )

        sys.exit(1)

