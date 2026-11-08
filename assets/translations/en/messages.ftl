# Menu
msg-language-select =
    <b>🌐 Bot language</b>

    Choose your interface language. Your choice will be saved for future visits.

msg-main-menu =
    { hdr-user-profile }
    { frg-user }

    { hdr-subscription }
    { $status ->
    [ACTIVE]
    { frg-subscription }
    [EXPIRED]
    <blockquote>
    • Expired.

    <i>{ $is_trial ->
    [0] Your subscription has expired. Renew it to continue using the service!
    *[1] Your free trial has ended. Get a subscription to continue using the service!
    }</i>
    </blockquote>
    [LIMITED]
    <blockquote>
    • You have used all your traffic.
    { frg-subscription-traffic-reset }

    <i>{ $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Renew your subscription to reset traffic and continue using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also renew your subscription to reset traffic.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Get a subscription to continue using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also get a subscription to use the service without restrictions.
        }
    }</i>
    </blockquote>
    [DISABLED]
    <blockquote>
    • Your subscription is disabled.

    <i>Contact support to find out why!</i>
    </blockquote>
    *[NONE]
    <blockquote>
    • You do not have a subscription.

    <i>{ $trial_available ->
    [1] 🎁 A free trial is available for you — tap the button below to claim it.
    *[0] ↘️ To purchase access, open the “Subscription” menu.
    }</i>
    </blockquote>
    }

msg-menu-devices =
    <b>📱 Manage devices</b>

    Connected: <b>{ $current_count } / { $max_count ->
    [0] { unlimited }
    *[LIMIT] { $max_count }
    }</b>

    { $has_devices ->
    [0] { empty }
    *[HAS] { $device_single_enabled ->
        [0] Contact support to unlink a device.
        *[OTHER] Tap a device to remove it.
        }
    }{ $max_count ->
    [0] { space }
    *[LIMIT] { space }If you need a higher device limit, change your subscription.
    }

msg-menu-devices-confirm-reissue =
    🔄 <b>Reissue subscription</b>

    ⚠️ After the reset, the old link <b>will stop working</b> and you will need to reconnect all devices.

    You will need to:
    • Remove the old subscription from your app
    • Add the new link from the “{ btn-menu.connect }” section

    Are you sure you want to reset the link?

msg-menu-devices-confirm-delete =
    🗑 <b>Confirm device removal</b>

    <b>{ $device_model }</b>
    <blockquote>
    • <b>Platform</b>: { $platform_icon } { $platform }
    • <b>Added</b>: { $created_at }
    </blockquote>

msg-menu-devices-confirm-delete-all =
    🗑 <b>Confirm removal of all devices</b>

msg-menu-invite =
    <b>👥 Invite friends</b>

    Share your unique link and receive rewards in the form of { $reward_type ->
        [POINTS] <b>points you can exchange for a subscription or real money</b>
        [EXTRA_DAYS] <b>free days added to your subscription</b>
        *[OTHER] { $reward_type }
    }!

    <b>📊 Statistics</b>:
    <blockquote>
    👥 Total invited: { $referrals }
    💳 Payments through your link: { $payments }
    { $reward_type ->
    [POINTS] 💎 Your points: { $points }
    *[EXTRA_DAYS] { empty }
    }
    </blockquote>

frg-referral-payment-condition = { $accrual_strategy ->
    [ON_FIRST_PAYMENT] first payment
    [ON_FIRST_PAYMENT_AND_INVITATION] first payment
    *[OTHER] every payment
    }

msg-menu-invite-about =
    <b>🎁 About the rewards</b>

    <b>✨ How to earn a reward</b>:
    <blockquote>
    { $accrual_strategy ->
    [ON_FIRST_PAYMENT] You receive a reward when an invited user purchases their first subscription.
    [ON_EACH_PAYMENT] You receive a reward every time an invited user purchases or renews a subscription.
    [ON_INVITATION] You receive a one-time reward when a new friend registers using your invite link.
    [ON_FIRST_PAYMENT_AND_INVITATION] You receive a separate reward when a new friend registers using your link and another reward for their first subscription purchase.
    [ON_EACH_PAYMENT_AND_INVITATION] You receive a separate reward when a new friend registers using your link and rewards for every subscription purchase or renewal they make.
    *[OTHER] { $accrual_strategy }
    }
    </blockquote>

    <b>💎 What you receive</b>:
    <blockquote>
    { $invitation_enabled ->
    [1] 👥 For an invitation: { $invitation_reward }
    *[0] { empty }
    }
    { $payment_rewards_enabled ->
    [1]
    { $max_level ->
    [1] For your friends' { frg-referral-payment-condition }: { $reward_level_1 }
    *[MORE]
    { $identical_reward ->
    [0]
    1️⃣ For your friends' { frg-referral-payment-condition }: { $reward_level_1 }
    2️⃣ For their friends' { frg-referral-payment-condition }: { $reward_level_2 }
    *[1]
    For your friends' and their friends' { frg-referral-payment-condition }: { $reward_level_1 }
    }
    }

    { $reward_strategy_type ->
    [AMOUNT] { $reward_type ->
        [POINTS] { space }
        [EXTRA_DAYS] <i>(All extra days are added to your current subscription)</i>
        *[OTHER] { $reward_type }
    }
    [PERCENT] { $reward_type ->
        [POINTS] <i>(Points calculated as a percentage of the price of their subscription)</i>
        [EXTRA_DAYS] <i>(Extra days calculated as a percentage of their subscription duration)</i>
        *[OTHER] { $reward_type }
    }
    *[OTHER] { $reward_strategy_type }
    }
    *[0] { empty }
    }
    </blockquote>

msg-invite-reward = { $reward_strategy_type ->
    [AMOUNT] { $reward_type ->
        [POINTS] { $value }{ space }{ $value ->
            [one] point
            [few] points
            *[more] points
            }
        [EXTRA_DAYS] +{ $value }{ space }{ $value ->
            [one] day
            [few] days
            *[more] days
            }
        *[OTHER] { $value }{ space }{ $reward_type }
    }
    [PERCENT] { $value }% { $reward_type ->
        [POINTS] in points
        [EXTRA_DAYS] in days
        *[OTHER] { $reward_type }
    }
    *[OTHER] { $value }{ $reward_strategy_type }
    }


# Dashboard
msg-dashboard-main = <b>🛠 Dashboard</b>
msg-users-main = <b>👥 Users</b>
msg-broadcast-main = <b>📢 Broadcasts</b>
msg-statistics-main = <b>📊 Statistics</b>

msg-statistics-users =
    <b>👥 User statistics</b>

    <blockquote>
    • <b>Total</b>: { $total_users }
    • <b>New today</b>: { $new_users_daily }
    • <b>New this week</b>: { $new_users_weekly }
    • <b>New this month</b>: { $new_users_monthly }

    • <b>Subscribed</b>: { $users_with_subscription }
    • <b>Unsubscribed</b>: { $users_without_subscription }
    • <b>On a trial</b>: { $users_with_trial }
    </blockquote>

    <blockquote>
    • <b>Blocked users</b>: { $blocked_users }
    • <b>Blocked the bot</b>: { $bot_blocked_users }

    • <b>User → purchase conversion</b>: { $user_conversion }%
    • <b>Trial → subscription conversion</b>: { $trial_conversion }%
    </blockquote>

msg-statistics-subscriptions =
    { $plan_name ->
    [0] <b>💳 Subscription statistics</b>
    *[HAS] <b>📦 Statistics for plan “{ $plan_name }”</b>
    }

    <blockquote>
    • <b>Total</b>: { $total }
    • <b>Active</b>: { $total_active }
    • <b>Disabled</b>: { $total_disabled }
    • <b>Limited</b>: { $total_limited }
    • <b>Expired</b>: { $total_expired }
    • <b>Expiring soon (7 days)</b>: { $expiring_soon }
    { $plan_name ->
    [0] • <b>Trials</b>: { $active_trial }
    *[HAS] • <b>Most popular duration</b>: { $popular_duration }
    }
    </blockquote>

    { $plan_name ->
    [0] <blockquote>
    • <b>Unlimited</b>: { $total_unlimited }
    • <b>With a traffic limit</b>: { $total_traffic }
    • <b>With a device limit</b>: { $total_devices }
    </blockquote>
    *[HAS] <b>Total revenue</b>:
    <blockquote>
    { $all_income }
    </blockquote>
    }

msg-statistics-subscriptions-plan-income = { $income }{ $currency }

msg-statistics-transactions =
    { $gateway_type ->
    [0] <b>🧾 Overall transaction statistics</b>
    *[HAS] <b>🧾 { gateway-type } statistics</b>
    }

    <blockquote>
    • <b>Total transactions</b>: { $total_transactions }
    • <b>Completed transactions</b>: { $completed_transactions }
    • <b>Free transactions</b>: { $free_transactions }
    { $gateway_type ->
    [0] { $popular_gateway ->
        [0] { empty }
        *[HAS] • <b>Most popular payment provider</b>: { $popular_gateway }
        }
    *[HAS] { empty }
    }
    </blockquote>

    { $gateway_type ->
    [0] { empty }
    *[HAS] <blockquote>
    • <b>Total revenue</b>: { $total_income }{ $currency }
    • <b>Revenue today</b>: { $daily_income }{ $currency }
    • <b>Revenue this week</b>: { $weekly_income }{ $currency }
    • <b>Revenue this month</b>: { $monthly_income }{ $currency }
    • <b>Revenue last month</b>: { $last_month_income }{ $currency }
    • <b>Average payment</b>: { $average_check }{ $currency }
    • <b>Total discounts</b>: { $total_discounts }{ $currency }
    </blockquote>
    }

msg-statistics-promocodes =
    <b>🎁 Promo code statistics</b>

    <blockquote>
    • <b>Total promo codes</b>: { $total_promocodes }
    • <b>Active</b>: { $active_promocodes }
    • <b>Total redemptions</b>: { $total_activations }
    </blockquote>

    <blockquote>
    • <b>Redemptions today</b>: { $activations_today }
    • <b>Redemptions this week</b>: { $activations_week }
    • <b>Redemptions this month</b>: { $activations_month }
    </blockquote>

    <blockquote>
    • <b>Days granted</b>: { $issued_days }
    • <b>Traffic granted (GB)</b>: { $issued_traffic }
    • <b>Devices granted</b>: { $issued_devices }
    • <b>Subscriptions granted</b>: { $issued_subscriptions }
    • <b>Personal discounts granted</b>: { $issued_personal_discounts }
    • <b>One-time discounts granted</b>: { $issued_purchase_discounts }
    </blockquote>

msg-statistics-promocode-detail =
    <b>🎁 Promo code</b> <code>{ $code }</code>

    <blockquote>
    • <b>Type</b>: { promocode-type }
    • <b>Reward</b>: { $reward }
    • <b>Status</b>: { $is_active ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
        }
    • <b>Repeated redemption</b>: { $is_reusable ->
        [1] Allowed
        *[0] Not allowed
        }
    </blockquote>

    <blockquote>
    • <b>Created</b>: { $created_at }
    • <b>Valid until</b>: { $expires_at }
    • <b>Redemption limit</b>: { $max_activations }
    • <b>Redemptions remaining</b>: { $remaining }
    </blockquote>

    <blockquote>
    • <b>Total redemptions</b>: { $total_activations }
    • <b>Today</b>: { $activations_today }
    • <b>This week</b>: { $activations_week }
    • <b>This month</b>: { $activations_month }
    </blockquote>

msg-statistics-referrals =
    <b>👪 Referral statistics</b>

    <blockquote>
    • <b>Total referrals</b>: { $total_referrals }
    • <b>Level 1</b>: { $level_1_count }
    • <b>Level 2</b>: { $level_2_count }
    • <b>Unique referrers</b>: { $unique_referrers }
    { $top_referrer_id ->
        [0] { empty }
        *[HAS] • <b>Top referrer</b>: { $top_referrer_telegram_id ->
            [0] <code>{ $top_referrer_email }</code>
            *[HAS] { $top_referrer_username ->
                [0] { NUMBER($top_referrer_telegram_id, useGrouping: 0) }
                *[HAS] <a href="tg://user?id={ $top_referrer_telegram_id }">@{ $top_referrer_username }</a>
            }
        } ({ $top_referrer_referrals_count } invited)
    }
    </blockquote>

    <blockquote>
    • <b>Rewards granted</b>: { $total_rewards_issued }
    • <b>Points granted</b>: { $total_points_issued }
    • <b>Days granted</b>: { $total_days_issued }
    </blockquote>


# Access
msg-access-main =
    <b>🔓 Access mode</b>

    <blockquote>
    • <b>Mode</b>: { access-mode }
    • <b>Payments</b>: { $payments_allowed ->
    [0] disabled
    *[1] enabled
    }.
    • <b>Registration</b>: { $registration_allowed ->
    [0] disabled
    *[1] enabled
    }.
    </blockquote>

msg-access-conditions =
    <b>⚙️ Access requirements</b>

msg-access-rules =
    <b>✳️ Change terms link</b>

    { $rules_url ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $rules_url }
    </blockquote>
    }

    Enter a link (in the format https://telegram.org/tos).

msg-access-channel =
    <b>❇️ Change channel/group link</b>

    { $channel_url ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $channel_url } { $channel_id ->
        [0] { empty }
        *[HAS] (ID: { $channel_id })
        }
    </blockquote>
    }

    If your group has no @username, send the group ID and invite link in separate messages.

    For a public channel/group, enter only its @username.


# Broadcast
msg-broadcast-list = <b>📄 Broadcast list</b>
msg-broadcast-repeat =
    <b>🔁 Repeat broadcast</b>

    Original broadcast: <code>{ $broadcast_id }</code>
    Choose who should receive the message again. You can configure exclusions in the next step.
    { $exclude_delivered ->
    [1] Users who have already received this broadcast or any of its repeats will be excluded automatically.
    *[0] All users in the selected audience will receive the message, including those who received it before.
    }
msg-broadcast-plan-select = <b>📦 Select a plan for the broadcast</b>
msg-broadcast-send = <b>📢 Send broadcast ({ audience-type })</b>

    { $audience_count } { $audience_count ->
    [one] user
    [few] users
    *[more] users
    } will receive the broadcast

    { $is_repeat ->
    [1] { $exclude_delivered ->
        [1] Repeat: new recipients only.
        *[0] Repeat: all selected users.
        }
    *[0] { empty }
    }

msg-broadcast-content =
    <b>✉️ Broadcast content</b>

    Send a message (HTML supported). You can attach a photo, video, or file. Limit: up to 4096 characters without media, or 1024 characters with media.

msg-broadcast-buttons = <b>✳️ Broadcast buttons</b>

msg-broadcast-custom-button =
    <b>🔗 Custom button</b>

    <blockquote>
    • <b>Text</b>: { $custom_button_text }
    • <b>Link</b>: { $custom_button_url }
    • <b>Ready</b>: { $custom_button_ready ->
        [1] ✅
        *[0] ❌ Specify the text and link
    }
    • <b>Enabled</b>: { $custom_button_enabled ->
        [1] ✅
        *[0] ❌
    }
    </blockquote>

    Use the toggle in the main button list to include this button in the broadcast.

msg-broadcast-custom-button-text =
    <b>✏️ Custom button text</b>

    Send button text up to 64 characters long.

msg-broadcast-custom-button-url =
    <b>🔗 Custom button link</b>

    Send a full HTTPS link, for example <code>https://example.com</code>.

msg-broadcast-excluded-users =
    <b>🚫 Broadcast exclusions</b>

    <blockquote>
    • <b>Telegram IDs specified</b>: { $excluded_users_count }
    • <b>ID</b>: <code>{ $excluded_user_ids }</code>
    • <b>By registration time</b>: { $registration_exclusion_days ->
        [7] accounts older than 7 days are excluded
        [30] accounts older than 30 days are excluded
        [90] accounts older than 90 days are excluded
       *[0] no exclusions
    }
    • <b>Recipients after exclusions</b>: { $audience_count }
    </blockquote>

    Choose the maximum account age using a button below. For example, a week excludes users who registered more than 7 days ago. A quarter is treated as 90 days.

    To specify a list, send users' Telegram IDs separated by spaces, commas, semicolons, or new lines. Duplicates are removed automatically. You can specify up to 1000 IDs.

msg-broadcast-view =
    <b>📢 Broadcast</b>

    <blockquote>
    • <b>ID</b>: <code>{ $broadcast_id }</code>
    • <b>Status</b>: { broadcast-status }
    • <b>Audience</b>: { audience-type }
    • <b>Created</b>: { $created_at }
    </blockquote>

    <blockquote>
    • <b>Total messages</b>: { $total_count }
    • <b>Successful</b>: { $success_count }
    • <b>Failed</b>: { $failed_count }
    </blockquote>


# Users
msg-users-recent-registered = <b>🆕 Recently registered</b>
msg-users-recent-activity = <b>📝 Recently active</b>
msg-user-transactions = <b>🧾 User transactions</b>
msg-user-devices = <b>📱 User devices ({ $current_count } / { $max_count })</b>
msg-user-give-access = <b>🔑 Grant plan access</b>

msg-users-search =
    <b>🔍 Find user</b>

    Enter the user's ID, email, or part of their name, or forward any of their messages.

msg-users-search-results =
    <b>🔍 Find user</b>

    Found <b>{ $count }</b> { $count ->
    [one] user
    [few] users
    *[more] users
    }, { $count ->
    [one] matching
    *[more] matching
    } the query

msg-user-main =
    <b>📝 User information</b>

    { hdr-user-profile }
    { frg-user-details }

    <b>💸 Discount</b>:
    <blockquote>
    • <b>Personal</b>: { $personal_discount }%
    • <b>Next purchase</b>: { $purchase_discount }%
    </blockquote>

    { hdr-subscription }
    { $status ->
    [ACTIVE]
    { frg-subscription-user-editor }
    [EXPIRED]
    <blockquote>
    • Expired.
    </blockquote>
    [LIMITED]
    <blockquote>
    • Traffic limit exceeded.
    </blockquote>
    [DISABLED]
    <blockquote>
    • Subscription disabled.
    </blockquote>
    *[NONE]
    <blockquote>
    • No current subscription.
    </blockquote>
    }

msg-user-statistics =
    <b>📊 User statistics</b>

    <blockquote>
    • <b>Registration date</b>: { $registered_at }
    • <b>Last payment</b>: { $last_payment_at ->
        [0] { unknown }
        *[HAS] { $last_payment_at }
    }
    </blockquote>

    { $payment_amounts ->
    [0] { space }
    *[HAS] <blockquote>
    { $payment_amounts }
    </blockquote>
    }

    <blockquote>
    • <b>Invited by</b>: { $referrer_telegram_id ->
        [0] { $referrer_email ->
            [0] { unknown }
            *[HAS] <code>{ $referrer_email }</code>
        }
        *[HAS] { $referrer_username ->
            [0] { NUMBER($referrer_telegram_id, useGrouping: 0) }
            *[HAS] <a href="tg://user?id={ $referrer_telegram_id }">@{ $referrer_username }</a>
        }
    }
    • <b>Invited (level 1)</b>: { $referrals_level_1 }
    • <b>Invited (level 2)</b>: { $referrals_level_2 }
    • <b>Points received</b>: { $reward_points }
    • <b>Days received</b>: { $reward_days }
    </blockquote>

msg-user-statistics-payment-amount = • <b>Paid ({ $currency })</b>: { $amount }

msg-user-referrals = <b>👪 User referrals</b>

msg-user-sync =
    <b>🌀 Synchronize user</b>

    <b>🛍 Remnashop</b>: { $bot_version }
    <blockquote>
    { $has_bot_subscription ->
    [0] No data
    *[HAS]{ $bot_subscription }
    }
    </blockquote>

    <b>🌊 Remnawave</b>: { $remna_version }
    <blockquote>
    { $has_remna_subscription ->
    [0] No data
    *[HAS] { $remna_subscription }
    }
    </blockquote>

    Choose a data source for synchronization.

msg-user-sync-version = { $version ->
    [NEWER] (newer)
    [OLDER] (older)
    *[UNKNOWN] { empty }
    }

msg-user-sync-subscription =
    • <b>ID</b>: <code>{ $id }</code>
    • Status: { $status ->
    [ACTIVE] Active
    [DISABLED] Disabled
    [LIMITED] Traffic exhausted
    [EXPIRED] Expired
    [DELETED] Deleted
    *[OTHER] { $status }
    }
    • Link: <a href="{ $url }">*********</a>

    • Traffic limit: { $traffic_limit }
    • Device limit: { $device_limit }
    • Time remaining: { $expire_time }

    • Internal squads: { $internal_squads ->
    [0] { unknown }
    *[HAS] { $internal_squads }
    }
    • External squad: { $external_squad ->
    [0] { unknown }
    *[HAS] { $external_squad }
    }
    • Traffic reset: { $traffic_limit_strategy ->
    [NO_RESET] On payment
    [DAY] Every day
    [WEEK] Every week
    [MONTH] Every month
    [MONTH_ROLLING] Every month (based on creation date)
    *[OTHER] { $traffic_limit_strategy }
    }
    • Tag: { $tag ->
    [0] { unknown }
    *[HAS] { $tag }
    }

msg-user-sync-waiting =
    <b>🌀 User synchronization</b>

    Please wait... User data is being synchronized. You will automatically return to the user editor when it finishes.

msg-user-give-subscription =
    <b>🎁 Grant subscription</b>

    Choose the plan you want to grant to the user.

msg-user-give-subscription-duration =
    <b>⏳ Select duration</b>

    Select the duration of the subscription to grant.

msg-user-discount =
    <b>💸 Edit discount</b>

    Select the type of discount to edit.

msg-user-discount-personal =
    <b>👤 Personal discount</b>

    Choose a button or enter a custom value.

msg-user-discount-purchase =
    <b>🎟 Next purchase discount</b>

    Choose a button or enter a custom value.
    The discount will be applied once and reset after any payment.

msg-user-points =
    <b>💎 Edit referral points</b>

    <b>Current points: { $current_points }</b>

    Choose a button or enter a custom value to add or subtract.

msg-user-subscription-traffic-limit =
    <b>🌐 Edit traffic limit</b>

    Choose a button or enter a custom value (in GB) to change the traffic limit.

msg-user-subscription-device-limit =
    <b>📱 Edit device limit</b>

    Choose a button or enter a custom value to change the device limit.

msg-user-subscription-expire-time =
    <b>⏳ Edit expiration time</b>

    <b>Expires in: { $expire_time }</b>

    Choose a button or enter a custom value (in days) to add or subtract.

msg-user-subscription-squads =
    <b>🔗 Edit squads</b>

    { $internal_squads ->
    [0] { empty }
    *[HAS] <b>⏺️ Internal</b>: { $internal_squads }
    }

    { $external_squad ->
    [0] { empty }
    *[HAS] <b>⏹️ External</b>: { $external_squad }
    }

msg-user-subscription-internal-squads =
    <b>⏺️ Edit internal squads</b>

    Choose which internal squads will be assigned to this user.

msg-user-subscription-external-squads =
    <b>⏹️ Edit external squad</b>

    Choose which external squad will be assigned to this user.

msg-user-subscription-info =
    <b>💳 Current subscription information</b>

    { hdr-subscription }
    { frg-subscription-details }

    <blockquote>
    • <b>Internal squads</b>: { $internal_squads ->
    [0] { unknown }
    *[HAS] { $internal_squads }
    }
    • <b>External squad</b>: { $external_squad ->
    [0] { unknown }
    *[HAS] { $external_squad }
    }
    • <b>First connection</b>: { $first_connected_at ->
    [0] { unknown }
    *[HAS] { $first_connected_at }
    }
    • <b>Last connection</b>: { $last_connected_at ->
    [0] { unknown }
    *[HAS] { $last_connected_at } ({ $node_name })
    }
    </blockquote>

    { hdr-plan }
    { frg-plan-snapshot }

msg-user-transaction-info =
    <b>🧾 Transaction information</b>

    { hdr-payment }
    <blockquote>
    • <b>ID</b>: <code>{ $payment_id }</code>
    • <b>User</b>: { $user_name } ({ $user_telegram_id ->
        [0] <code>{ $user_email }</code>
        *[HAS] <code>{ NUMBER($user_telegram_id, useGrouping: 0) }</code>
    })
    • <b>Type</b>: { purchase-type }
    • <b>Status</b>: { transaction-status }
    • <b>Payment method</b>: { gateway-type }
    • <b>Amount</b>: { frg-payment-amount }
    • <b>Created</b>: { $created_at }
    </blockquote>

    { $is_test ->
    [1] ⚠️ Test transaction
    *[0]
    { hdr-plan }
    { frg-plan-snapshot }
    }

msg-user-role =
    <b>👮‍♂️ Edit role</b>

    Select a new role for the user.

msg-users-blacklist =
    <b>🚫 Blocklist</b>

msg-users-blacklist-list =
    <b>📋 Blocked users</b>

    Blocked: <b>{ $count_blocked }</b> / <b>{ $count_users }</b> ({ $percent }%).

msg-users-blacklist-block =
    <b>⛔ Block by ID</b>

    Supported formats
    <blockquote>
    • <b>Text</b>: enter a single ID or a list of IDs
    • <b>Link</b>: send a URL containing a list of IDs
    • <b>File</b>: attach a .txt file containing a list of IDs
    </blockquote>

    For lists, put each ID on a new line.

    Blocking applies even if the user has never used the bot.

msg-users-blacklist-sources =
    <b>🔗 Auto-updated blocklists</b>

    Tap a list to delete it.
    Synchronization runs automatically every 6 hours.

    To add a new list, send a direct link to a text file containing Telegram IDs.

msg-user-message =
    <b>📩 Send a message to the user</b>

    Send any message: text, an image, or both (HTML supported).


# RemnaWave
msg-remnawave-main =
    <b>🌊 RemnaWave v{ $version }</b>

    <b>🖥️ System</b>:
    <blockquote>
    • <b>CPU</b>: { $cpu_cores } { $cpu_cores ->
    [one] core
    [few] cores
    *[more] cores
    }
    • <b>RAM</b>: { $ram_used } / { $ram_total } ({ $ram_used_percent }%)
    • <b>Uptime</b>: { $uptime }
    </blockquote>

msg-remnawave-users =
    <b>👥 Users</b>

    <b>📊 Statistics</b>:
    <blockquote>
    • <b>Total</b>: { $users_total }
    • <b>Active</b>: { $users_active }
    • <b>Disabled</b>: { $users_disabled }
    • <b>Limited</b>: { $users_limited }
    • <b>Expired</b>: { $users_expired }
    </blockquote>

    <b>🟢 Online</b>:
    <blockquote>
    • <b>In the last day</b>: { $online_last_day }
    • <b>In the last week</b>: { $online_last_week }
    • <b>Never connected</b>: { $online_never }
    • <b>Online now</b>: { $online_now }
    </blockquote>

msg-remnawave-host-details =
    <b>{ $remark } ({ $is_disabled ->
    [1] disabled
    *[0] enabled
    })</b>:
    <blockquote>
    • <b>Address</b>: <code>{ $address }:{ NUMBER($port, useGrouping: 0) }</code>
    { $inbound_uuid ->
    [0] { empty }
    *[HAS] • <b>Inbound</b>: <code>{ $inbound_uuid }</code>
    }
    </blockquote>

msg-remnawave-node-details =
    <b>{ $country } { $name } ({ $is_connected ->
    [1] connected
    *[0] disconnected
    })</b>:
    <blockquote>
    • <b>Address</b>: <code>{ $address }{ $port ->
    [0] { empty }
    *[HAS]:{ NUMBER($port, useGrouping: 0) }
    }</code>
    • <b>Uptime (xray)</b>: { $xray_uptime }
    • <b>Users online</b>: { $users_online }
    • <b>Traffic</b>: { $traffic_used } / { $traffic_limit }
    </blockquote>

msg-remnawave-inbound-details =
    <b>🔗 { $tag }</b>
    <blockquote>
    • <b>ID</b>: <code>{ $inbound_id }</code>
    • <b>Protocol</b>: { $type } { $network ->
    [0] { space }
    *[HAS] ({ $network })
    }
    { $port ->
    [0] { empty }
    *[HAS] • <b>Port</b>: { NUMBER($port, useGrouping: 0) }
    }
    { $security ->
    [0] { empty }
    *[HAS] • <b>Security</b>: { $security }
    }
    </blockquote>

msg-remnawave-hosts =
    <b>🌐 Hosts</b>

    { $is_empty ->
    [1] <i>No hosts</i>
    *[0] { $host }
    }

msg-remnawave-nodes =
    <b>🖥️ Nodes</b>

    { $is_empty ->
    [1] <i>No nodes</i>
    *[0] { $node }
    }

msg-remnawave-inbounds =
    <b>🔌 Inbounds</b>

    { $is_empty ->
    [1] <i>No inbounds</i>
    *[0] { $inbound }
    }


# RemnaShop
msg-remnashop-main = <b>🛍 RemnaShop { $version ->
[0] { space }
*[HAS] { $version }
}</b>

msg-remnashop-transactions = <b>🧾 Recent transactions</b>


# Backup
msg-backup-main =
    <b>💾 Automatic database backup</b>

    <blockquote>
    • <b>Status</b>: { $enabled ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
    }
    • <b>Send to chat</b>: { $send_to_chat ->
        [1] ✅ Enabled
        *[0] ❌ Disabled
    }
    • <b>Interval</b>:  { $interval_hours ->
    [one] every
    *[OTHER] every
    } { $interval_hours } h
    • <b>Number of files</b>: { $max_files }
    </blockquote>

msg-backup-set-interval =
    <b>🕐 Backup interval</b>

    Current value: <b>{ $interval_hours } h</b>

    Enter the backup interval in hours (1 to 720).

msg-backup-set-max-files =
    <b>📁 Number of files</b>

    Current value: <b>{ $max_files }</b>

    Enter how many backup files to keep (1 to 30). Older files will be deleted automatically.

msg-extra-main = <b>⚙️ Additional settings</b>

msg-extra-device-single =
    ⚙️ <b>Remove a single device</b>

    Allows users to remove a specific device from the list.

    <blockquote>
    <b>Status:</b> { $enabled ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
    }
    <b>Cooldown:</b> { $cooldown ->
        [0] { unknown }
        *[OTHER] { $cooldown } h
    }
    </blockquote>

    Enter a number to change the cooldown (in hours; 0 means no restrictions).

msg-extra-device-all =
    ⚙️ <b>Remove all devices</b>

    Allows users to remove all devices with one tap.

    <blockquote>
    <b>Status:</b> { $enabled ->
        [1] ✅ Enabled
        *[0] ❌ Disabled
    }
    <b>Cooldown:</b> { $cooldown ->
        [0] { unknown }
        *[OTHER] { $cooldown } h
    }
    </blockquote>

    Enter a number to change the cooldown (in hours; 0 means no restrictions).

msg-extra-link-reset =
    ⚙️ <b>Reissue subscription</b>

    Allows users to reissue the connection link (invalidating the old one).

    <blockquote>
    <b>Status:</b> { $enabled ->
        [1] ✅ Enabled
        *[0] ❌ Disabled
    }
    <b>Cooldown:</b> { $cooldown ->
        [0] { unknown }
        *[OTHER] { $cooldown } h
    }
    </blockquote>

    Enter a number to change the cooldown (in hours; 0 means no restrictions).

msg-extra-referral-reset =
    ⚙️ <b>Reset referral link</b>

    Allows users to change their referral link.

    <blockquote>
    <b>Status:</b> { $enabled ->
        [1] ✅ Enabled
        *[0] ❌ Disabled
    }
    <b>Cooldown:</b> { $cooldown ->
        [0] { unknown }
        *[OTHER] { $cooldown } h
    }
    </blockquote>

    Enter a number to change the cooldown (in hours; 0 means no restrictions).

msg-extra-trial-channel-guard =
    ⚙️ <b>Auto-disable trial when leaving the channel</b>

    If a user leaves the required channel/group during their trial, their subscription is automatically paused. Access is restored when they rejoin, provided the trial has not expired.

    <blockquote>
    <b>Status:</b> { $enabled ->
        [1] ✅ Enabled
        *[0] ❌ Disabled
    }
    </blockquote>

    Works only when channel/group membership is required.

msg-extra-mini-app-reserve =
    ⚙️ <b>Backup connection button when Mini App is active</b>

    Adds a backup button below the main “Connect” button (which opens the Mini App). It opens the subscription page in a browser. Useful in regions where Telegram Mini Apps may be blocked.

    <blockquote>
    <b>Status:</b> { $enabled ->
        [1] ✅ Enabled
        *[0] ❌ Disabled
    }
    </blockquote>

    Works only when Mini App is enabled (BOT_MINI_APP).

msg-admins-main = <b>👮‍♂️ Administrators</b>


# Menu editor
msg-menu-editor-main =
    <b>🎛 Main menu button editor</b>

    Select a button to edit.

msg-menu-editor-button =
    <b>🎛 Button configuration</b>

    <blockquote>
    • <b>Status</b>: { $is_active ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
        }
    • <b>Text</b>: { $text }
    • <b>Access</b>: { role }
    • <b>Visibility</b>: { $subscribers_only ->
        [1] 🔒 Subscribers only
        *[0] 👥 All users
        }
    • <b>Type</b>: { button-type }
    • <b>Color</b>: { $color ->
        [primary] Primary
        [success] Green
        [danger] Red
        *[OTHER] No color
        }
    { $type ->
        [TEXT] { empty }
       *[OTHER] • <b>Data</b>: { $payload }
    }
    </blockquote>

    Select a setting to edit.

msg-menu-editor-button-text =
    <b>🏷️ Edit button text</b>

    Enter button text (up to 32 characters) or a translation key.

msg-menu-editor-button-availability =
    <b>✴️ Edit button access</b>

    Select the role required to access the button.

msg-menu-editor-button-type =
    <b>🔖 Edit button type</b>

    Select a button type.

msg-menu-editor-button-payload =
    <b>📄 Edit button data</b>

    { $button_type ->
        [URL] Enter a link. It must start with <code>https://</code>.
        [COPY] Enter the text to copy to the clipboard when the button is tapped.
        [WEB_APP] Enter a web app link. It must start with <code>https://</code>; <code>t.me</code> links are not supported.
        *[TEXT] Send a message (HTML supported). You can attach a photo, video, file, or sticker. Limit: up to 4096 characters without media, or 1024 characters with media.
    }

msg-menu-editor-button-color =
    <b>🎨 Edit button color</b>

    Select a button color.


# Gateways
msg-gateways-main = <b>🌐 Payment providers</b>
msg-gateways-settings = <b>🌐 { gateway-type } configuration</b>
msg-gateways-default-currency = <b>💸 Default currency</b>
msg-gateways-placement = <b>🔢 Change order</b>

msg-gateways-field =
    <b>🌐 { gateway-type } configuration</b>

    Enter a new value for { $field ->
        [display_name] the display name
        [autopay_display_name] the auto-payment method name
        [payment_timeout_minutes] the payment timeout in minutes (a positive integer)
       *[other] { $field }
    }.

    { $field ->
        [payment_timeout_minutes] Current value: { $payment_timeout_minutes } min.
            Default: 60 min. After the timeout, a pending payment is canceled during the next status check.
            The payment link's validity period is set by FlipPay.
       *[other] { empty }
    }

msg-flippay-methods =
    <b>💳 FlipPay payment methods</b>

    Select a method to change its customer-facing name or enable it individually.
    🟢 Enabled · 🔴 Disabled · ⚪ Unavailable for this merchant

    “Refresh from FlipPay” loads your merchant's payment methods. New methods are disabled by default; your custom names and toggles are retained.
    { $methods_loaded ->
        [0] The list has not been loaded yet. The previously configured method is still being used.
       *[other] { empty }
    }

msg-flippay-method =
    <b>💳 FlipPay payment method</b>

    Method: { $method_name }
    Customer-facing name: { $method_title }
    Minimum amount: { $minimum } ₽
    ID: <code>{ $method_id }</code> · Code: <code>{ $method_code }</code>
    { $available ->
        [1] { $enabled ->
            [1] 🟢 Enabled
           *[other] 🔴 Disabled
            }
       *[other] ⚪ Unavailable for this merchant. Refresh the list after enabling the method in FlipPay.
    }

    Disabling hides the method for new purchases. Existing payments continue to be processed.

msg-flippay-method-name =
    <b>🏷️ Payment method name</b>

    Method: { $method_name }
    Current name: { $method_title }
    Send a new customer-facing name. “Reset value” restores the name from FlipPay.

msg-rivara-methods =
    <b>💳 Rivara Pay payment methods</b>

    The general option opens the Rivara Pay page with all available payment methods.
    For separate buttons, enable the required types: SBP, Russian bank cards, international cards, or cryptocurrency.

    The general option and individual types are mutually exclusive: enabling the general option disables individual types, and enabling an individual type disables the general option.
    🟢 Enabled · 🔴 Disabled

    Select a method to enable it or change its customer-facing name.

msg-rivara-method =
    <b>💳 Rivara Pay payment method</b>

    Method: { $method_name }
    Customer-facing name: { $method_title }
    { $enabled ->
        [1] 🟢 Enabled
       *[other] 🔴 Disabled
    }

    { $is_general ->
        [1] The customer can choose any available method on the Rivara Pay page.
       *[other] Only this payment type will be available on the Rivara Pay page.
    }

    Disabling hides the method for new purchases. Existing payments continue to be processed.

msg-rivara-method-name =
    <b>🏷️ Payment method name</b>

    Method: { $method_name }
    Current name: { $method_title }
    Send a new customer-facing name. “Reset value” restores the default name.

msg-gateways-autopay-note =
    SBP auto-payments: a separate payment method that links a bank account.
    Disabling this option hides new auto-payment setup. Users can stop existing recurring charges in their subscription settings.


# Referral
msg-referral-main =
    <b>👥 Referral system</b>

    <blockquote>
    • <b>Status</b>: { $is_enable ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
        }
    • <b>Reward type</b>: { reward-type }
    • <b>Number of levels</b>: { $referral_level }
    • <b>Reward trigger</b>: { accrual-strategy }
    { $payment_rewards_enabled ->
    [1] • <b>Payment reward calculation</b>: { reward-strategy }
    *[0] { empty }
    }
    { $invitation_enabled ->
    [1] • <b>For an invitation</b>: { $invitation_reward }
    *[0] { empty }
    }
    </blockquote>

    Select a setting to edit.

msg-referral-level =
    <b>🔢 Edit level</b>

    Select the maximum referral level.

msg-referral-reward-type =
    <b>🎀 Edit reward type</b>

    Select a new reward type.

msg-referral-accrual-strategy =
    <b>📍 Edit reward trigger</b>

    Select when rewards are granted.


msg-referral-reward-strategy =
    <b>⚖️ Edit reward calculation</b>

    Select how rewards are calculated.


msg-referral-reward-level = Level { $level }: { msg-invite-reward }

msg-referral-invitation-reward =
    <b>👥 Invitation reward</b>

    <blockquote>For an invitation: { $invitation_reward }</blockquote>

    Enter the number of { $reward_type ->
        [POINTS] points
        [EXTRA_DAYS] days
        *[OTHER] { $reward_type }
    } from 1 to 100000.

    The reward is granted once when a new friend registers using the link, only to the person who invited them. It is a fixed amount configured separately from payment rewards.

msg-referral-reward =
    <b>🎁 Payment reward</b>

    <blockquote>
    { $reward }
    </blockquote>

    { $reward_strategy_type ->
        [AMOUNT] Enter the number of { $reward_type ->
            [POINTS] points
            [EXTRA_DAYS] days
            *[OTHER] { $reward_type }
        }
        [PERCENT] Enter a percentage of { $reward_type ->
            [POINTS] <u>the subscription price</u>
            [EXTRA_DAYS] <u>the subscription duration</u>
            *[OTHER] { $reward_type }
        }
        *[OTHER] { $reward_strategy_type }
    } (in the format: level=value)


# Plans
msg-plans-main = <b>📦 Plans</b>

msg-plans-import =
    <b>📦 Import plans</b>

    Send a JSON file to import.

msg-plans-export =
    <b>📦 Export plans</b>

    Select the plans to export.

msg-plan-configurator =
    <b>📦 Plan configuration</b>

    <blockquote>
    • <b>Name</b>: { $name }
    • <b>Type</b>: { plan-type } { $is_trial ->
    [1] (Trial)
    *[0] { space }
    }
    • <b>Access</b>: { availability-type }
    • <b>Status</b>: { $is_active ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
        }
    </blockquote>

    <blockquote>
    • <b>Traffic limit</b>: { $is_unlimited_traffic ->
        [1] { unlimited }
        *[0] { $traffic_limit }
        }
    • <b>Device limit</b>: { $is_unlimited_devices ->
        [1] { unlimited }
        *[0] { $device_limit }
        }
    </blockquote>

    Select a setting to edit.

msg-plan-name =
    <b>🏷️ Edit name</b>

    { $name ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $name }
    </blockquote>
    }

    Enter a unique plan name or translation key (up to 32 characters).

msg-plan-description =
    <b>💬 Edit description</b>

    { $description ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $description }
    </blockquote>
    }

    Enter a new plan description or translation key.

msg-plan-tag =
    <b>📌 Edit tag</b>

    { $tag ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $tag }
    </blockquote>
    }

    Enter a new plan tag (uppercase Latin letters, digits, and underscores only).

msg-plan-type =
    <b>🔖 Edit type</b>

    Select a new plan type. Enable “Trial” to offer this plan as a trial.

msg-plan-availability =
    <b>✴️ Edit availability</b>

    Select the plan's availability.

msg-plan-traffic =
    <b>🌐 Edit traffic limit and reset strategy</b>

    Enter a new plan traffic limit (in GB) and select its reset strategy.

msg-plan-devices =
    <b>📱 Edit device limit</b>

    Enter a new device limit for the plan.

msg-plan-durations =
    <b>⏳ Plan durations</b>

    Select a duration to edit its price.

msg-plan-duration =
    <b>⏳ Add plan duration</b>

    Enter a new duration (in days).

msg-plan-prices =
    <b>💰 Edit prices for duration ({ $value ->
            [0] { unlimited }
            *[OTHER] { unit-day }
        })</b>

    Select the currency whose price you want to edit.

msg-plan-price =
    <b>💰 Edit price for duration ({ $value ->
            [0] { unlimited }
            *[OTHER] { unit-day }
        })</b>

    Enter a new price in { $currency }.

msg-plan-allowed-users =
    <b>👥 Edit allowed users</b>

    Enter a user's ID or email to add them to the list.

msg-plan-squads =
    <b>🔗 Squads</b>

    { $internal_squads ->
    [0] { space }
    *[HAS] <b>⏺️ Internal</b>: { $internal_squads }
    }

    { $external_squad ->
    [0] { space }
    *[HAS] <b>⏹️ External</b>: { $external_squad }
    }

msg-plan-internal-squads =
    <b>⏺️ Edit internal squads</b>

    Choose which internal squads will be assigned to this plan.

msg-plan-external-squads =
    <b>⏹️ Edit external squad</b>

    Choose which external squad will be assigned to this plan.


# Notifications
msg-notifications-main = <b>🔔 Notification settings</b>
msg-notifications-user = <b>👥 User notifications</b>
msg-notifications-system = <b>⚙️ System notifications</b>

msg-notifications-system-type =
    <b>🔔 { notification-type }</b>

    <blockquote>
    • <b>Status</b>: { $is_active ->
    [1] 🟢 Enabled
    *[0] 🔴 Disabled
    }
    • <b>Route</b>: { $has_route ->
    [0] { unknown }
    *[HAS] { NUMBER($chat_id, useGrouping: 0) }{ $thread_id ->
        [0] { space }
        *[HAS] :{ NUMBER($thread_id, useGrouping: 0) }
        }
    }
    </blockquote>

msg-notifications-system-route =
    <b>📡 Route: { notification-type }</b>

    <blockquote>
    • <b>Chat ID</b>: { $chat_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($chat_id, useGrouping: 0) }</code>
        }
    • <b>Thread ID</b>: { $thread_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($thread_id, useGrouping: 0) }</code>
        }
    </blockquote>

    If no chat ID is set, the notification will be sent as a direct message.

    If no thread ID is set, the notification will be sent to the chat.


msg-notifications-system-default-route =
    <b>📡 Default route</b>

    <blockquote>
    • <b>Chat ID</b>: { $chat_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($chat_id, useGrouping: 0) }</code>
        }
    • <b>Thread ID</b>: { $thread_id ->
        [0] { unknown }
        *[HAS] <code>{ NUMBER($thread_id, useGrouping: 0) }</code>
        }
    </blockquote>

    This route applies to all system notifications without their own route.

    If no chat ID is set, the notification will be sent as a direct message.

    If no thread ID is set, the notification will be sent to the chat.


msg-notifications-system-route-chat-id =
    <b>💬 Edit chat ID</b>

    Enter the group ID (for example: <code>-1001234567891</code>).

msg-notifications-system-route-thread-id =
    <b>📁 Edit thread ID</b>

    Enter the thread ID (enter <code>0</code> to reset).


# Subscription
msg-subscription-main = <b>💳 Subscription</b>
msg-subscription-plans = <b>📦 Select a plan</b>
msg-subscription-new-success = To start using our service, tap <code>`{ btn-subscription.connect }`</code> and follow the instructions!
msg-subscription-renew-success = Your subscription has been extended by { $added_duration }.

msg-subscription-plan =
    <b>📦 Plan available via link</b>

    The <b>{ $name }</b> plan is available to you through this link. Tap the button below to select a duration and payment method.

    { $description ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $description }
    </blockquote>
    }

    { $purchase_type ->
    [RENEW] <i>⚠️ Your current subscription will be <u>extended</u> by the selected duration.</i>
    [CHANGE] <i>⚠️ Your current subscription will be <u>replaced</u> with this plan without adjusting for the remaining time.</i>
    *[OTHER] { empty }
    }

msg-subscription-details =
    <b>{ $plan }</b>:
    <blockquote>
    { $description ->
    [0] { empty }
    *[HAS]
    { $description }
    }

    • <b>Traffic limit</b>: { $traffic }
    • <b>Device limit</b>: { $devices }
    { $period ->
    [0] { empty }
    *[HAS] • <b>Duration</b>: { $period }
    }
    { $final_amount ->
    [0] { empty }
    *[HAS] • <b>Price</b>: { frg-payment-amount }
    }
    </blockquote>

    { $discount_percent ->
    [0] { empty }
    *[HAS]
    <blockquote>
    <i>Prices include { $is_personal_discount ->
        [1] your personal discount of { $discount_percent }%
        *[0] a one-time discount of { $discount_percent }%
        }</i>
    </blockquote>
    }

msg-subscription-duration =
    <b>⏳ Select duration</b>

    { msg-subscription-details }

    { $plan_is_modified ->
    [1] <i>ℹ️ The plan terms have changed since your last purchase — the current details are shown above.</i>
    *[0] { "" }
    }

msg-subscription-payment-method =
    <b>💳 Select a payment method</b>

    { msg-subscription-details }

    { $plan_is_modified ->
    [0] { empty }
    *[MODIFIED] <i>ℹ️ The plan terms have changed since your last purchase — the current details are shown above.</i>
    }

msg-subscription-confirm =
    <b>🛒 Confirm subscription { $purchase_type ->
    [RENEW] renewal
    [CHANGE] change
    *[OTHER] purchase
    }</b>

    { msg-subscription-details }

    { $purchase_type ->
    [RENEW] <i>⚠️ Your current subscription will be <u>extended</u> by the selected duration.</i>
    [CHANGE] <i>⚠️ Your current subscription will be <u>replaced</u> with the selected one without adjusting for the remaining time.</i>
    *[OTHER] { empty }
    }

    { $plan_is_modified ->
    [0] { empty }
    *[MODIFIED] <i>ℹ️ The plan terms have changed since your last purchase — the current details are shown above.</i>
    }

msg-subscription-trial =
    <b>✅ Trial subscription activated!</b>

    { msg-subscription-new-success }

msg-subscription-success =
    <b>✅ Payment successful!</b>

    { $purchase_type ->
    [NEW] { msg-subscription-new-success }
    [RENEW] { msg-subscription-renew-success }
    [CHANGE] { msg-subscription-change-success }
    *[OTHER] { $purchase_type }
    }

msg-subscription-change-success =
    Your subscription has been changed.

    <b>{ $plan_name }</b>
    { frg-subscription }

msg-subscription-failed =
    <b>❌ An error occurred!</b>

    Do not worry — support has already been notified and will contact you shortly. We apologize for the inconvenience.


# Importer
msg-importer-main = <b>📥 Import users</b>

msg-importer-from-xui =
    <b>📥 Import users (3X-UI)</b>

    { $has_exported ->
    [1]
    <b>🔍 Found</b>:
    <blockquote>
    Total users: { $total }
    With an active subscription: { $active }
    With an expired subscription: { $expired }
    </blockquote>
    *[0]
    All <b>active</b> users with a <b>numeric</b> email are imported.

    We recommend disabling users whose email field does not contain a Telegram ID beforehand. This operation may take a significant amount of time depending on the number of users.

    Send the database file (in .db format).
    }

msg-importer-squads =
    <b>🔗 Internal squads</b>

    Choose which internal squads will be available to imported users.

msg-importer-import-completed =
    <b>📥 User import completed</b>

    <b>📃 Information</b>:
    <blockquote>
    • <b>Total users</b>: { $total_count }
    • <b>Imported successfully</b>: { $success_count }
    • <b>Import failed</b>: { $failed_count }
    </blockquote>

msg-importer-sync-panel =
    <b>🌀 Synchronization: panel → bot</b>

    Processes all users in RemnaWave. If a user is missing from the bot, creates them and imports their subscription. If a user exists in the bot without a subscription, imports it from the panel. If a user already has a subscription in the bot, updates their data.

msg-importer-sync-bot =
    <b>🤖 Synchronization: bot → panel</b>

    Processes all bot users. Users without a subscription in the bot are skipped, leaving the panel unchanged. If a user has a subscription but is missing from the panel, creates them. If a user exists in the panel, updates their data.

msg-importer-sync-panel-completed =
    <b>📥 Panel → bot synchronization completed</b>

    <b>📃 Information</b>:
    <blockquote>
    Total users in the panel: { $total_panel_users }
    Total users in the bot: { $total_bot_users }

    New users: { $added_users }
    Subscriptions added: { $added_subscription }
    Subscriptions updated: { $updated }

    Synchronization errors: { $errors }
    </blockquote>

msg-importer-sync-bot-completed =
    <b>🔄 Bot → panel synchronization completed</b>

    <b>📃 Information</b>:
    <blockquote>
    Total users in the bot: { $total_bot_users }

    Updated in the panel: { $updated }
    Recreated in the panel: { $recreated }

    Without a subscription (skipped): { $skipped_no_subscription }
    Synchronization errors: { $errors }
    </blockquote>


# Promocodes
msg-promocodes-main = <b>🎟 Promo codes</b>

msg-promocode-configurator =
    <b>🎟 Promo code configuration</b>

    <blockquote>
    • <b>Code</b>: <code>{ $code }</code>
    • <b>Type</b>: { promocode-type }
    • <b>Access</b>: { availability-type }
    • <b>Status</b>: { $is_active ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
        }
    • <b>Repeated redemption</b>: { $is_reusable ->
        [1] Allowed
        *[0] Not allowed
        }
    </blockquote>

    <blockquote>
    • <b>Reward</b>: { $reward }
    • <b>Valid until</b>: { $expires }
    • <b>Redemption limit</b>: { $max_activations }
    </blockquote>

    Select a setting to edit.

msg-promocode-input-code =
    <b>🏷️ Edit code</b>

    { $code ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $code }
    </blockquote>
    }

    Send your unique code (3 to 16 characters).

msg-promocode-select-type =
    <b>🔖 Edit reward type</b>

    Select a reward type.

msg-promocode-input-reward =
    <b>🎁 Edit reward</b>

    { $reward ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $reward }
    </blockquote>
    }

    { $promocode_type ->
    [DURATION] Enter the number of <b>days</b> to add to the user's subscription upon redemption (a value of <code>0</code> makes the subscription permanent).
    [TRAFFIC] Enter the number of <b>gigabytes (GB)</b> to add to the subscription's traffic limit (a value of <code>0</code> makes traffic unlimited).
    [DEVICES] Enter the number of <b>devices</b> to add to the subscription limit (a value of <code>0</code> removes the device limit).
    [PERSONAL_DISCOUNT] Enter the <b>personal discount</b> percentage, from 1 to 100.
    [PURCHASE_DISCOUNT] Enter the <b>purchase discount</b> percentage, from 1 to 100.
    *[OTHER] Enter the reward value (an integer).
    }

msg-promocode-select-plan =
    <b>📦 Edit plan</b>

    Select a subscription plan.

msg-promocode-select-plan-duration =
    <b>⏳ Edit duration</b>

    Select the plan duration.

msg-promocode-select-availability =
    <b>✴️ Edit availability</b>

    Select the promo code's availability.

msg-promocode-input-expires =
    <b>⌛ Valid until</b>

    { $expires ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $expires }
    </blockquote>
    }

    Enter a date as “DD.MM.YYYY” (or with a time as “DD.MM.YYYY HH:MM”), or a number of days from creation.

    Time is specified in UTC.

msg-promocode-input-max-activations =
    <b>🔢 Edit redemption limit</b>

    { $max_activations ->
    [0] { space }
    *[HAS]
    <blockquote>
    { $max_activations }
    </blockquote>
    }

    Enter the maximum number of redemptions.

msg-promocode-input =
    <b>🎟 Promo code</b>

    Enter a promo code.

msg-promocode-confirm =
    <b>🎟 Promo code <code>{ $promo_code }</code></b>

    🎁 Your reward: { $reward_type ->
        [DURATION] { $reward ->
            [0] your current subscription will <b>never expire</b>.
            *[OTHER] <b>{ $reward } { $reward ->
                [one] day
                [few] days
                *[more] days
            }</b> added to your current subscription.
        }
        [TRAFFIC] { $reward ->
            [0] <b>unlimited traffic</b> on your current subscription.
            *[OTHER] <b>{ $reward } GB</b> added to your traffic limit.
        }
        [DEVICES] { $reward ->
            [0] <b>unlimited devices</b> on your current subscription.
            *[OTHER] <b>{ $reward } { $reward ->
                [one] device
                [few] devices
                *[more] devices
            }</b> added to your device limit.
        }
        [SUBSCRIPTION] a <b>new plan</b> for your subscription.
        [PERSONAL_DISCOUNT] a permanent <b>{ $reward }% discount</b> on all purchases.
        [PURCHASE_DISCOUNT] a <b>{ $reward }% discount</b> on your next purchase.
        *[OTHER] a reward for your account.
    }

    { $show_reset_warning ->
        [1] ⚠️ <i>This bonus lasts until your next subscription renewal — the limit will then return to the plan's default.</i>
       *[0] { space }
    }
    { $will_replace_subscription ->
        [1] ⚠️ <i>You already have an active subscription. It will be replaced with the new plan, and your remaining days and traffic will be reset.</i>
       *[0] { space }
    }

    Tap <b>Confirm</b> to redeem.


# Ad Links
msg-ad-links-main = <b>🎯 Advertising links</b>

msg-ad-link-configurator =
    <b>🎯 Advertising link configuration</b>

    <blockquote>
    • <b>Name</b>: { $name ->
        [0] not set
        *[HAS] { $name }
    }
    • <b>Code</b>: { $code ->
        [0] not set
        *[HAS] <code>{ $code }</code>
    }
    • <b>Status</b>: { $is_active ->
        [1] 🟢 Enabled
        *[0] 🔴 Disabled
    }
    </blockquote>

    Select a setting to edit.

msg-ad-link-name =
    <b>🏷️ Link name</b>

    { $name ->
    [0] { space }
    *[HAS]
    <blockquote>{ $name }</blockquote>
    }

    Enter the advertising campaign name.

msg-ad-link-code =
    <b>🔗 Link code</b>

    Current: <code>{ $code }</code>

    Send your unique code or tap the button.

msg-ad-link-stats =
    <b>📊 Statistics: { $name }</b>

    <blockquote>
    • <b>Registrations</b>: { $registrations }
    • <b>Trials</b>: { $trials }
    • <b>Purchases</b>: { $buyers }

    • <b>Registration → purchase conversion</b>: { $reg_to_buy_rate }%
    • <b>Trial → purchase conversion</b>: { $trial_to_buy_rate }%
    </blockquote>

    <blockquote>
    { $revenue_lines }
    </blockquote>
