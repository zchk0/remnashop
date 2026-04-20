# `Banners`

The `banners` folder contains all banner images.

## Banner configuration

You can configure how banners are displayed in the bot using an environment variable:

* **`BOT_USE_BANNERS`**: Set to true to enable banners, or false to disable them.

## Locale support

The banner system supports **localized versions**. A banner corresponding to the user's **locale** will be loaded for each user. Available locales are defined by the `APP_LOCALES` environment variable.

### How it works:

When loading a banner, the system searches in the following order:

1. `banners/{user_locale}/{page}` — page-specific banner for the user’s locale
2. `banners/{user_locale}/default` — default banner for the user’s locale
3. `banners/{default_locale}/{page}` — page-specific banner for the default locale (`APP_DEFAULT_LOCALE`)
4. `banners/{default_locale}/default` — default banner for the default locale
5. `banners/default` — global fallback

Steps 3–4 handle the case where a user’s locale is not supported — the system falls back to the default locale’s banners before using the global default.

This means:
- To use **one image everywhere** — place a single `banners/default.jpg`.
- To use **one image per locale** — place `banners/{locale}/default.jpg` for each locale.
- To use **per-page images** — place `banners/{locale}/{page}.jpg` for each page and locale.

This ensures that even if a specific banner or locale is not found, some banner will always be displayed, preventing empty or missing images.

## Supported formats

The following file formats are supported, as defined in `/remnashop/src/core/enums.py` as `BannerFormat`:

* **JPG**
* **JPEG**
* **PNG**
* **GIF**
* **WEBP**

## Banner names

Banner filenames must correspond to the following predefined names, specified in `/remnashop/src/core/enums.py` as `BannerName`:

* **`DEFAULT`**: The default banner, used when a specific banner is not found.
* **`MENU`**: The main menu banner.
* **`DASHBOARD`**: The dashboard banner.
* **`SUBSCRIPTION`**: The subscription banner.
* **`REFERRAL`**: The referral banner.

## Example file structure

```
banners/
├── default.jpg       ← global default (used for all pages and locales as last fallback)
├── ru/
│   ├── default.jpg   ← default for all pages in ru locale
│   ├── menu.jpg      ← page-specific banner for ru locale
│   └── subscription.jpg
└── en/
    ├── default.jpg   ← default for all pages in en locale
    └── menu.jpg
```


# `Translations`

The `translations` folder contains all localization text files.

## Translation configuration

Supported locales are defined in environment variables:

* **`APP_LOCALES`**: A list of supported locales. A full list of available locales can be found in `remnashop/src/core/enums.py` as `Locale`.
* **`APP_DEFAULT_LOCALE`**: The default locale to be used if a user's language preference is not specified or not supported.


## Key naming convention

All translation keys must follow a unified structure:
```
{category}-{scope}-{entity}-{action-or-state}
```

## Components

| Part                | Description                   | Example                                                                            |
| ------------------- | ----------------------------- | ---------------------------------------------------------------------------------- |
| `{category}`        | Top-level type of text        | `btn`, `msg`, `ntf`                                                                |
| `{scope}`           | Logical group or subsystem    | `user`, `plan`, `broadcast`, `gateway`, `subscription`, `access`, `error`, `event` |
| `{entity}`          | Specific object or sub-entity | `content`, `payment`, `link`, `node`                                               |
| `{action-or-state}` | Action or state, in lowercase | `created`, `deleted`, `empty`, `invalid`, `failed`, `not-found`                    |

## Naming rules

1. Use lowercase with hyphens (-) — no underscores or spaces.
2. Follow the order:
    ```
    category → scope → entity → action/state
    ```
    - ✅ ntf-broadcast-content-empty
    - ✅ btn-user-create
    - ✅ msg-plan-deleted-success

    - ❌ ntf-content-empty-broadcast
    - ❌ btn-create-user
    - ❌ msg-plan-success-deleted
3. Actions — past tense verbs (created, updated, deleted, canceled, failed).
4. States — adjectives (empty, invalid, not-found, expired, not-available).
5. Limit to 5 segments maximum (recommended).
6. Keep the total key length under 32 characters (recommended).

## Examples keys

| Purpose                               | Key                               |
| ------------------------------------- | --------------------------------- |
| Notification: user expired            | `ntf-user-expired`                |
| Notification: broadcast empty content | `ntf-broadcast-content-empty`     |
| Button: confirm deletion              | `btn-plan-confirm-delete`         |
| Message: plan created successfully    | `msg-plan-created-success`        |
| Notification: gateway test failed     | `ntf-gateway-test-payment-failed` |


## `custom.ftl`

Each locale folder may contain a `custom.ftl` file (e.g. `translations/ru/custom.ftl`). This file is intended for user-defined translations that are not part of the standard set — such as custom menu buttons, plan names, and similar entries.

### Usage

Add key-value pairs to the file using the standard Fluent syntax:

```
key-name = Translation text
```

Then use the key wherever text is expected (e.g. in a plan name or menu link). The system will resolve it to the translated string at runtime.

### Constraints

| Context      | Max length      |
| ------------ | --------------- |
| Buttons      | 32 characters   |
| Messages     | 1024 characters |

### Key naming

Keys must be **unique** and should follow the general naming convention described above. To avoid collisions with built-in keys, prefix custom keys with `custom-`:

```
custom-menu-link1 = 1️⃣ First button
custom-plan-name1 = Basic plan
```

### Example file

```ftl
# Custom menu buttons
custom-menu-link1 = 1️⃣ First button
custom-menu-link2 = 2️⃣ Second button

# Custom plan names
custom-plan-name1 = 1️⃣ Basic plan
custom-plan-name2 = 2️⃣ Premium plan
```


# `Custom Emoji`

Telegram supports custom emoji in buttons. To use them, the bot must have a paid username (Fragment) or the bot owner must have an active Telegram Premium subscription.

## How to get an emoji ID

1. Send the desired custom emoji to [@getidsbot](https://t.me/getidsbot) or `@RawDataBot`.
2. The bot will return message details including the `custom_emoji_id`.

## Syntax

Two formats are supported directly in `.ftl` key values.

### Full format

```ftl
btn-example = <tg-emoji emoji-id="5406756500108501710">🎁</tg-emoji> Button text
```

### Short format

```ftl
btn-example = <e id="5406756500108501710">🎁</e> Button text
```

The fallback text inside the tag (a plain emoji) is shown on clients that don't support custom emoji. It is recommended to always provide it.

## Usage in buttons

Both formats are automatically recognized by the `Emoji*` widgets (`EmojiButton`, `EmojiSwitchTo`, `EmojiBack`, etc.) when rendering keyboards. The custom emoji is extracted from the key text and passed as `icon_custom_emoji_id` on the Telegram button — it is a separate field, not part of the label.

Example in `buttons.ftl`:

```ftl
btn-menu =
    .connect = <tg-emoji emoji-id="5447410659077661506">🚀</tg-emoji> Connect
    .devices = <e id="5271604874419647061">📱</e> Devices
```

## Usage in messages

Custom emoji can be used in message text via the `I18nFormat` widget. The short format `<e id="...">` is automatically expanded to the full `<tg-emoji>` tag before the text is sent.

```ftl
msg-broadcast-main = <tg-emoji emoji-id="5424818078833715060">📢</tg-emoji> <b>Broadcast</b>
msg-statistics-main = <e id="5231200819986047254">📊</e> <b>Statistics</b>
```

## Emoji priority

If a button already has `icon_custom_emoji_id` set via the widget's `Style` (aiogram-dialog `Style(icon_custom_emoji_id="...")`), it takes priority over the emoji from the key text.

---

# `QR Code Logo`

You can customize the appearance of the generated invitation QR code by adding your logo to the center of the code.

* **Path:** `assets/logo.png`
* **Purpose:** If this file exists, the system will use it as a logo, overlaying it in the center of the generated QR code image for branding purposes.
* **Format:** The logo must be a `PNG` file, preferably with a transparent background.