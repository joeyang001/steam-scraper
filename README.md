# Steam Scraper — Games, Prices & Reviews (No Login)

Scrape the **Steam store**: search for games, pull **full app details** and collect **player reviews** — without logging in, without an API key and without a browser.

Every row is normalized, de-duplicated and carries provenance, ready for spreadsheets, databases, dashboards or LLM pipelines.

## What you get

- **Store search** — give search terms and get matching games, each enriched with full details.
- **Direct apps** — pass app IDs or store URLs to fetch specific games.
- **Full details** — price + discount, genres, categories, platforms, release date, developers/publishers, Metacritic, recommendation counts, achievements, screenshots, DLC, languages.
- **Player reviews** — cursor-paginated, with votes, weighted score, playtime, purchase type and per-app review summary.

All rows live in one dataset, tagged by `record_type` (`game` or `review`).

## Output fields

**Games (`record_type: "game"`)**
| Field | Description |
|---|---|
| `app_id` / `name` / `app_type` | Identity |
| `release_date` / `is_coming_soon` / `required_age` | Release info |
| `developers` / `publishers` | Studios |
| `genres` / `categories` | Tags |
| `platforms_windows` / `platforms_mac` / `platforms_linux` | Platforms |
| `price_currency` / `price_initial` / `price_final` / `price_discount_percent` / `price_formatted` / `is_discounted` | Price (minor units, e.g. cents) |
| `metacritic_score` / `recommendations_total` / `achievements_total` | Scores & counts |
| `short_description` / `detailed_description` / `about_the_game` | Text (detail optional) |
| `header_image` / `capsule_image` / `background` / `screenshots` / `movie_count` / `dlc` | Media |
| `store_url` / `source_type` / `source_input` / `schema_version` / `fetched_at` | Provenance |

**Reviews (`record_type: "review"`)**
| Field | Description |
|---|---|
| `recommendation_id` / `app_id` | Identity |
| `review_text` / `language` / `voted_up` | Content |
| `votes_up` / `votes_funny` / `weighted_vote_score` / `comment_count` | Engagement |
| `timestamp_created` / `timestamp_updated` | ISO-8601 UTC + epoch |
| `steam_purchase` / `received_for_free` / `refunded` / `written_during_early_access` / `primarily_steam_deck` | Flags |
| `author_steamid` / `author_personaname` / `author_profile_url` / `author_num_games_owned` / `author_num_reviews` / `author_playtime_forever` / `author_playtime_at_review` | Author |
| `review_score_desc` / `review_score` / `total_positive` / `total_negative` / `total_reviews` | Summary |

## Use cases

- **Game market research** — pricing, discounts, genre trends, release cadence.
- **Publisher & studio analytics** — reception and sentiment per title.
- **Review sentiment / AI datasets** — clean, structured review text with metadata.
- **Price tracking & deal monitoring** — watch discounts across regions.
- **Player/author profiling** — playtime and ownership for market studies.

## Input

```json
{
  "searchQueries": ["co-op roguelike", "city builder"],
  "appIds": [1145360],
  "includeReviews": true,
  "maxReviewsPerApp": 200,
  "reviewFilter": "recent",
  "country": "US"
}
```

## Pricing

**Pay per result.** You are charged only for rows delivered to your dataset (games and reviews), plus a small per-run fee. No subscription, no minimum.

## Notes

- Uses Steam's public store endpoints (`/search/results/`, `/api/appdetails`, `/appreviews/`); `store.steampowered.com/robots.txt` allows these paths.
- De-duplicated across searches and app IDs.
- Steam occasionally rate-limits high request volumes; the Actor paces its requests. Intended for research and analytics — use in line with Steam's terms.
