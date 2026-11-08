space = {" "}
empty = { "!empty!" }
btn-test = Button
msg-test = Message
development = Under development!
test-payment = Test payment
unknown = —

msg-device-auth-token-not-found = Authorization token not found or expired.
msg-device-auth-already-authorized = You are already authorized.
msg-device-auth-trial-not-available = A trial is unavailable for this Telegram account.
msg-device-auth-trial-plan-not-available = The trial plan is currently unavailable.
msg-device-auth-trial-create-failed = Could not create a trial subscription. Try again later.
msg-device-auth-device-limit-reached =
    You have reached your subscription's device limit: { $device_limit }.
    Remove a device or change your subscription.
msg-device-auth-linking-failed =
    Could not finish linking your account.
    Try again in a few seconds.
msg-device-auth-success =
    🧩 Authorization successful!

    Return to the ToBeVPN app.
    Open it manually or use the DeepLink:
    tobevpn.meowbot.ru

development-promocode = Promo codes have not been implemented yet. You can donate to support and speed up development.
raw-message = { $content }

payment-invoice-description = { purchase-type } of the { $name } subscription for { $duration }

ad-link-default-name = New link
plan-default-name = New plan

platform-icon =
    .ios = 🍎
    .android = 🤖
    .windows = 🖥️
    .macos = 💻
    .linux = 🐧
    .default = 📱

inline-invite =
    .title = Invite a friend
    .description = Tap to send an invite link!
    .message =
        Hi! Want a fast, reliable VPN?

        { $bot_name } can help!

        ↘️ TAP THE BUTTON AND TRY IT FOR FREE!
    .start = 🚀 Join

message =
    .withdraw-points = My code: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
        Hello! I would like to exchange my points.
    .paysupport = My code: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
        Hello! I would like to request a refund.
    .help = My code: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
        Hello! I need help.

command =
    .start = Restart the bot
    .tasks = Open tasks
    .language = Change language
    .paysupport = Request a refund
    .rules = Terms of Service
    .help = Help

hdr-user = <b>👤 User</b>:
hdr-user-profile = <b>👤 Profile</b>:
hdr-payment = <b>💰 Payment</b>:
hdr-error = <b>⚠️ Error</b>:
hdr-node = <b>🖥 Node</b>:
hdr-hwid = <b>📱 Device</b>:

hdr-subscription = { $is_trial ->
    [1] <b>🎁 Trial subscription</b>:
    *[0] <b>💳 Subscription</b>:
}

hdr-plan = { $is_trial_plan ->
    [1] <b>🎁 Trial plan</b>:
    *[0] <b>📦 Plan</b>:
}

frg-user =
    <blockquote>
    { $telegram_id ->
        [0] • <b>Email</b>: <code>{ $email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $name }
    { $show_personal_discount ->
    [1] • <b>Personal discount</b>: { $personal_discount }%
    *[0] { empty }
    }
    { $show_purchase_discount ->
    [1] • <b>Purchase discount</b>: { $purchase_discount }%
    *[0] { empty }
    }
    </blockquote>

frg-user-info =
    <blockquote>
    { $telegram_id ->
        [0] • <b>Email</b>: <code>{ $email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $name } { $username ->
        [0] { empty }
        *[HAS] (<a href="tg://user?id={ $telegram_id }">@{ $username }</a>)
    }
    </blockquote>

frg-user-details =
    <blockquote>
    { $telegram_id ->
        [0] • <b>Email</b>: <code>{ $email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $name } { $username ->
        [0] { space }
        *[HAS] (<a href="tg://user?id={ $telegram_id }">@{ $username }</a>)
    }
    • <b>Role</b>: { role }
    • <b>Language</b>: { language }
    • <b>Bot blocked</b>: { $is_bot_blocked ->
        [1] Yes
        *[0] No
    }
    { $show_points ->
    [1] • <b>Points</b>: { $points }
    *[0] { empty }
    }
    </blockquote>

frg-subscription =
    <blockquote>
    • <b>Traffic limit</b>: { $traffic_limit }
    { frg-subscription-traffic-reset }
    • <b>Device limit</b>: { $device_limit }
    • <b>Time remaining</b>: { $expire_time }
    { $has_subscription_url ->
    [1] &#160;
    ⬇️ CONNECTION LINK:
    <b>URL</b>: <code>{ $subscription_url }</code>
    *[0] { empty }
    }
    </blockquote>

frg-subscription-traffic-reset =
    { $next_reset_at ->
    [0] { empty }
    *[DATE] • <b>Traffic reset</b>: { $next_reset_at }
    }

frg-subscription-user-editor =
    <blockquote>
    • <b>Plan</b>: { $plan_name }
    • <b>Traffic limit</b>: { $traffic_limit }
    • <b>Device limit</b>: { $device_limit }
    • <b>Time remaining</b>: { $expire_time }
    </blockquote>

frg-subscription-details =
    <blockquote>
    • <b>ID</b>: <code>{ $subscription_id }</code>
    • <b>Status</b>: { subscription-status }
    • <b>Traffic</b>: { $traffic_used } / { $traffic_limit }
    • <b>Device limit</b>: { $device_limit }
    • <b>Time remaining</b>: { $expire_time }
    </blockquote>

frg-payment-info =
    <blockquote>
    • <b>ID</b>: <code>{ $payment_id }</code>
    • <b>Payment method</b>: { gateway-type }
    • <b>Amount</b>: { frg-payment-amount }
    </blockquote>

frg-payment-amount = { $final_amount }{ $currency } { $discount_percent ->
    [0] { space }
    *[more] { space } <strike>{ $original_amount }{ $currency }</strike> (-{ $discount_percent }%)
    }

frg-plan-snapshot =
    <blockquote>
    • <b>Plan</b>: <code>{ $plan_name }</code>
    • <b>Type</b>: { plan-type }
    • <b>Traffic limit</b>: { $plan_traffic_limit }
    • <b>Device limit</b>: { $plan_device_limit }
    • <b>Duration</b>: { $plan_duration }
    </blockquote>

frg-plan-snapshot-comparison =
    <blockquote>
    • <b>Plan</b>: <code>{ $previous_plan_name }</code> -> <code>{ $plan_name }</code>
    • <b>Type</b>: { $previous_plan_type } -> { plan-type }
    • <b>Traffic limit</b>: { $previous_plan_traffic_limit } -> { $plan_traffic_limit }
    • <b>Device limit</b>: { $previous_plan_device_limit } -> { $plan_device_limit }
    • <b>Duration</b>: { $previous_plan_duration } -> { $plan_duration }
    </blockquote>

frg-node-info =
    <blockquote>
    • <b>Name</b>: { $country } { $name }
    • <b>Address</b>: <code>{ $address }{ $port ->
    [0] { space }
    *[HAS] :{ NUMBER($port, useGrouping: 0) }
    }</code>
    • <b>Traffic</b>: { $traffic_used } / { $traffic_limit }
    { $last_status_message ->
    [0] { empty }
    *[HAS] • <b>Last status</b>: { $last_status_message }
    }
    { $last_status_change ->
    [0] { empty }
    *[HAS] • <b>Status changed</b>: { $last_status_change }
    }
    </blockquote>

frg-user-hwid =
    <blockquote>
    • <b>HWID</b>: <code>{ $hwid }</code>
    { $platform ->
    [0] { space }
    *[HAS] • <b>Platform</b>: { $platform }
    }
    { $device_model ->
    [0] { space }
    *[HAS] • <b>Model</b>: { $device_model }
    }
    { $os_version ->
    [0] { space }
    *[HAS] • <b>Version</b>: { $os_version }
    }
    { $user_agent ->
    [0] { space }
    *[HAS] • <b>User agent</b>: { $user_agent }
    }
    </blockquote>

frg-build-info =
    { $has_build ->
    [0] { space }
    *[HAS]
    <b>🏗️ Build information</b>:
    <blockquote>
    Build time: { $time }
    Branch: { $branch } ({ $tag })
    Commit: <a href="{ $commit_url }">{ $commit }</a>
    </blockquote>
    }

frg-promocode-reward = { $promocode_type ->
    [DURATION] { $reward ->
        [0] { unlimited } days
        [one] { $reward } day
        [few] { $reward } days
        *[more] { $reward } days
        } added to the current subscription
    [TRAFFIC] { $reward ->
        [0] { unlimited } GB
        *[OTHER] { $reward } GB
        } added to the current subscription
    [DEVICES] { $reward ->
        [0] { unlimited } devices
        [one] { $reward } device
        [few] { $reward } devices
        *[more] { $reward } devices
        } added to the current subscription
    [SUBSCRIPTION] { $plan_name } subscription
    [PERSONAL_DISCOUNT] { $reward }% added to the personal discount
    [PURCHASE_DISCOUNT] { $reward }% added to the next purchase discount
    *[OTHER] { $reward }
    }

role-owner = Owner
role-dev = Developer
role-admin = Administrator
role-preview = Observer
role-user = User
role =
    { $role ->
    [5] { role-owner }
    [4] { role-dev }
    [3] { role-admin }
    [2] { role-preview }
    *[1] { role-user }
}

unlimited = ∞

unit-unlimited = { $value ->
    [0] { unlimited }
    *[OTHER] { $value }
}

unit-device = { $value ->
    [0] { unlimited }
    *[OTHER] { $value }
} { $value ->
    [0] { space }
    [one] device
    [few] devices
    *[OTHER] devices
}

unit-byte = { $value } B
unit-kilobyte = { $value } KB
unit-megabyte = { $value } MB
unit-gigabyte = { $value } GB
unit-terabyte = { $value } TB

unit-second = { $value } { $value ->
    [one] second
    [few] seconds
    *[OTHER] seconds
}

unit-minute = { $value } { $value ->
    [one] minute
    [few] minutes
    *[OTHER] minutes
}

unit-hour = { $value } { $value ->
    [one] hour
    [few] hours
    *[OTHER] hours
}

unit-day = { $value } { $value ->
    [one] day
    [few] days
    *[OTHER] days
}

unit-month = { $value } { $value ->
    [one] month
    [few] months
    *[OTHER] months
}

unit-year = { $value } { $value ->
    [one] year
    [few] years
    *[OTHER] years
}


plan-type = { $plan_type ->
    [TRAFFIC] Traffic
    [DEVICES] Devices
    [BOTH] Traffic + devices
    [UNLIMITED] Unlimited
    *[OTHER] { $plan_type }
}

promocode-type = { $promocode_type ->
    [DURATION] Duration
    [TRAFFIC] Traffic
    [DEVICES] Devices
    [SUBSCRIPTION] Subscription
    [PERSONAL_DISCOUNT] Personal discount
    [PURCHASE_DISCOUNT] Purchase discount
    *[OTHER] { $promocode_type }
}

availability-type = { $availability_type ->
    [ALL] Everyone
    [NEW] New users
    [EXISTING] Existing users
    [INVITED] Invited users
    [ALLOWED] Allowed users
    [LINK] Via link
    *[OTHER] { $availability_type }
}

gateway-type = { $gateway_type ->
    [TELEGRAM_STARS] Telegram Stars
    [YOOKASSA] YooKassa
    [YOOMONEY] YooMoney
    [CRYPTOMUS] Cryptocurrency (Cryptomus)
    [HELEKET] Heleket
    [CRYPTOPAY] CryptoPay
    [FREEKASSA] FreeKassa
    [MULENPAY] MulenPay
    [PAYMASTER] PayMaster
    [PLATEGA] Platega
    [ROBOKASSA] RoboKassa
    [URLPAY] UrlPay
    [WATA] WATA
    [VALUTIX] Valutix
    [FLIPPAY] FlipPay
    [RIVARAPAY] Rivara Pay
    *[OTHER] { $gateway_type }
}

access-mode = { $access_mode ->
    [PUBLIC] 🟢 Open to everyone
    [INVITED] 🟡 Open to invited users
    [RESTRICTED] 🔴 Closed to everyone
    *[OTHER] { $access_mode }
}

audience-type = { $audience_type ->
    [ALL] Everyone
    [PLAN] By plan
    [SUBSCRIBED] Subscribed
    [UNSUBSCRIBED] Unsubscribed
    [EXPIRED] Expired subscriptions
    [TRIAL] Trial users
    *[OTHER] { $audience_type }
}

broadcast-status = { $broadcast_status ->
    [PROCESSING] In progress
    [COMPLETED] Completed
    [CANCELED] Canceled
    [DELETED] Deleted
    [ERROR] Error
    *[OTHER] { $broadcast_status }
}

transaction-status = { $transaction_status ->
    [PENDING] Pending
    [COMPLETED] Completed
    [CANCELED] Canceled
    [REFUNDED] Refunded
    [FAILED] Failed
    *[OTHER] { $transaction_status }
}

subscription-status = { $subscription_status ->
    [ACTIVE] Active
    [DISABLED] Disabled
    [LIMITED] Traffic exhausted
    [EXPIRED] Expired
    [DELETED] Deleted
    *[OTHER] { $subscription_status }
}

purchase-type = { $purchase_type ->
    [NEW] Purchase
    [RENEW] Renewal
    [CHANGE] Change
    *[OTHER] { $purchase_type }
}

traffic-strategy = { $strategy_type ->
    [NO_RESET] On payment
    [DAY] Every day
    [WEEK] Every week
    [MONTH] Every month
    [MONTH_ROLLING] Every month (based on creation date)
    *[OTHER] { $strategy_type }
    }

reward-type = { $reward_type ->
    [POINTS] Points
    [EXTRA_DAYS] Days
    *[OTHER] { $reward_type }
    }

accrual-strategy = { $accrual_strategy_type ->
    [ON_FIRST_PAYMENT] First payment
    [ON_EACH_PAYMENT] Every payment
    [ON_INVITATION] Invitation
    [ON_FIRST_PAYMENT_AND_INVITATION] First payment + invitation
    [ON_EACH_PAYMENT_AND_INVITATION] Every payment + invitation
    *[OTHER] { $accrual_strategy_type }
    }

reward-strategy = { $reward_strategy_type ->
    [AMOUNT] Fixed
    [PERCENT] Percentage
    *[OTHER] { $reward_strategy_type }
    }

button-type = { $button_type ->
    [URL] Open link
    [COPY] Copy text
    [WEB_APP] Open web app
    [TEXT] Send message
    *[OTHER] { $button_type }
}

notification-type = { $notification_type ->
    [SYSTEM] System
    [EXPIRES_IN_3_DAYS] Subscription expires (3 days)
    [EXPIRES_IN_2_DAYS] Subscription expires (2 days)
    [EXPIRES_IN_1_DAY] Subscription expires (1 day)
    [EXPIRED] Subscription expired
    [EXPIRED_1_DAY_AGO] Subscription expired (1 day ago)
    [LIMITED] Traffic exhausted
    [REFERRAL_ATTACHED] Referral attached
    [REFERRAL_REWARD_RECEIVED] Referral reward
    [REFERRAL_REWARD_FAILED] Reward delivery failed
    [BOT_LIFECYCLE] Bot lifecycle
    [BOT_UPDATE] Bot updates
    [USER_REGISTERED] User registration
    [SUBSCRIPTION] Subscription purchase
    [PROMOCODE_ACTIVATED] Promo code redemption
    [TRIAL_ACTIVATED] Trial activation
    [EARNING_TASK_COMPLETED] Task completion
    [NODE_STATUS_CHANGED] Node status
    [NODE_TRAFFIC_REACHED] Node traffic
    [TORRENT_BLOCKER] Torrent detection
    [USER_FIRST_CONNECTION] First connection
    [USER_DEVICES_UPDATED] User devices
    [USER_REVOKED_SUBSCRIPTION] Subscription reset
    [NOT_CONNECTED] No connection
    [TORRENT_BLOCKED] Torrent restriction
    [BLACKLIST_ATTEMPT] User registration (blocklisted)
    *[OTHER] { $notification_type }
    }

language = { $language ->
    [ar] Arabic
    [az] Azerbaijani
    [be] Belarusian
    [cs] Czech
    [de] German
    [en] English
    [es] Spanish
    [fa] Persian
    [fr] French
    [he] Hebrew
    [hi] Hindi
    [id] Indonesian
    [it] Italian
    [ja] Japanese
    [kk] Kazakh
    [ko] Korean
    [ms] Malay
    [nl] Dutch
    [pl] Polish
    [pt] Portuguese
    [ro] Romanian
    [ru] Russian
    [sr] Serbian
    [tr] Turkish
    [uk] Ukrainian
    [uz] Uzbek
    [vi] Vietnamese
    *[OTHER] { $language }
}
