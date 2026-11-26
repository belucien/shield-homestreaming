# Shield Home Streaming

An ad-free, cinematic home screen for the NVIDIA Shield using **Projectivy Launcher (Premium)**.

- **Carousel:** about 20 titles for Stremio: series with a new episode this week, brand-new series premiering soon, movies coming soon, and new movies out on digital. Refreshed every 30 minutes. Each one shows its backdrop, logo, year, rating, runtime, genres, a short description, and "Watch on Stremio" or its premiere date.
- **Weather:** live conditions for Rancho Cucamonga (91730), with the high, low, and chance of rain, built into each wallpaper.
- **Clock and date:** Projectivy's own clock, so it's always exact, e.g. `1:05` over `WEDNESDAY 11/25`.
- **Apps:** your streaming apps in a single dock along the bottom.

Everything runs free on GitHub. Nothing has to stay running on your computer.

```
TMDB (movies/TV) ─┐
Open-Meteo (weather)┼─► GitHub Actions, every 30 min ─► GitHub Pages ─► Overflight plugin ─► Projectivy
```

---

## Part 1: One-time setup on your computer (about 15 minutes)

### 1. Get a free TMDB key
1. Create an account at https://www.themoviedb.org/signup.
2. Go to **Settings → API** (https://www.themoviedb.org/settings/api) and request a **Developer** key. It's free for personal use. Fill in the short form; for the website you can enter your GitHub page.
3. Copy the **API Read Access Token** (the long one that starts with `eyJ`). The shorter "API Key" works too.

### 2. Put this project on GitHub
1. Create an account at https://github.com if you don't have one.
2. Create a **new public repository** named `shield-homestreaming` (already done). Leave it empty: no README, no license.
3. Upload the files in this folder. Or tell Claude the repo name and it will push the files for you.

> GitHub Pages hosting is free for public repositories. The only things that become public are the wallpapers and the weather for your city. Your TMDB key stays private as a secret.

### 3. Add your TMDB key as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `TMDB_API_KEY`
- Secret: paste the token from step 1

### 4. Turn on GitHub Pages
Repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**

### 5. Run it for the first time
Repo → **Actions → Update wallpapers → Run workflow**. It takes about 2 minutes. Then open:

```
https://belucien.github.io/shield-homestreaming/
```

You should see a gallery of the generated wallpapers. Your feed URL for the Shield is:

```
https://belucien.github.io/shield-homestreaming/overflight.json
```

---

## Part 2: On the Shield (about 10 minutes)

### 6. Make Projectivy your home screen
Projectivy Settings → turn on **Override current launcher**. Pressing Home now opens Projectivy instead of the Google TV screen with ads.

### 7. Install the wallpaper plugin
1. Install **Overflight (Projectivy Plugin)** from the Google Play Store on the Shield. It needs Premium, which you have.
2. Projectivy Settings → **Appearance → Wallpaper** → choose **Overflight**.
3. Open the Overflight plugin settings:
   - **Custom URL:** your `overflight.json` URL from step 5
   - **Format:** 4K (every entry points to the same 4K image)
   - **HTTP cache:** the shortest option, so new weather and titles show up quickly
4. In Projectivy's wallpaper settings:
   - Set the **refresh/rotation interval** to how long each title stays on screen. 1–2 minutes feels like a carousel.
   - Turn **off** wallpaper blur and dimming, since the wallpapers already have their own shading.

### 8. Clock and date (top-right)
Projectivy Settings → **Appearance → Clock** (Projectivy 4.70 or newer):
- Use a **two-line** clock format: the time on line 1 and the date on line 2.
- Date pattern: `EEEE MM/dd` gives `WEDNESDAY 11/25` (with uppercase on). Use `EEE MM/dd` for `WED 11/25`. These are standard Android date patterns. If your version shows a list of presets instead, pick the one closest to "weekday + month/day".
- Make the time large and the date small, with white tint and a soft shadow.
- The wallpapers leave the top-right corner empty for the clock.

### 9. App dock (bottom)
1. Create one category, e.g. "Apps", and add Hulu, Kodi, Nuvio, YouTube, Apple TV, Disney+, Prime Video, ESPN, MLB, NBA and Peacock in the order you want.
2. Hide every other category or row: recommendations, "Now playing", Live TV, and so on.
3. Turn on the **category background (dock)** and give it a dark, slightly transparent look.
4. Hide app names under the icons if you want it more minimal, like the inspiration photo.
5. Optional: Appearance → Font → pick a clean sans-serif such as Inter or Roboto so it matches the wallpapers.

When you're done: **Settings → Themes → Export** saves your whole setup as a backup.

---

## Customizing

Edit `config.json` in the repo. Saving the change on GitHub rebuilds the wallpapers automatically.

| Setting | What it does |
| --- | --- |
| `weather` | Location (lat/long), city label, `fahrenheit`/`celsius` |
| `mix` | How many of each kind: `just_aired_tv`, `new_movies`, `upcoming_tv`, `upcoming_movies` |
| `watch_label` | The app named in "Watch on …" (Stremio) |
| `original_languages` | Limit to these languages, e.g. `["en"]`; use `[]` for all (anime, K-drama…) |
| `output_width/height` | 3840×2160 by default. Use 1920×1080 if your TV is 1080p, for smaller files |

To refresh right away: **Actions → Update wallpapers → Run workflow**.

## Good to know

- **How current is the weather?** It's regenerated every 30 minutes, and the Shield reloads the list about once an hour, so expect it to be up to about an hour behind. The "UPDATED" time on screen tells you exactly how old it is. The clock is always exact because Projectivy draws it.
- **Arrows:** Projectivy rotates wallpapers on its own timer. You can't flip through them with the remote.
- **Paused schedule:** GitHub pauses scheduled jobs in public repos after 60 days with no commits, and emails you first. Click **Enable workflow** in the Actions tab, or make any small edit, to restart it.
- **Run your own copy offline:** `pip install -r requirements.txt && python generate.py --demo --out site` renders sample wallpapers without any keys.

## Credits

- Movie and TV data and images: [TMDB](https://www.themoviedb.org). This product uses the TMDB API but is not endorsed or certified by TMDB. Streaming availability: JustWatch, via TMDB.
- Weather: [Open-Meteo](https://open-meteo.com) (CC BY 4.0).
- Font: Inter (SIL Open Font License, see `fonts/LICENSE-Inter.txt`).
