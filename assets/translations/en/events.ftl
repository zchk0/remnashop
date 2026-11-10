event-error =
    .general =
    #ErrorEvent

    <b>🔅 Event: An error occurred!</b>

    { frg-build-info }

    { $telegram_id ->
    [0] { space }
    *[HAS]
    { hdr-user }
    { frg-user-info }
    }

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .payment-timeout =
    #ErrorEvent

    <b>⏱ Event: Payment gateway timeout!</b>

    { frg-build-info }

    { $telegram_id ->
    [0] { space }
    *[HAS]
    { hdr-user }
    { frg-user-info }
    }

    { hdr-error }
    <blockquote>
    • <b>Payment gateway</b>: { gateway-type }
    • <b>Reason</b>: { $timeout_phase ->
        [connect] Timed out while connecting to the API.
        [read] Timed out while waiting for the API response.
        [write] Timed out while sending the request to the API.
        [pool] Timed out while waiting for an available API connection.
        *[OTHER] The API request timed out.
    }
    • <b>Request</b>: <code>{ $request_method } { $request_host }</code>
    { $has_timeout ->
    [1] • <b>Timeout limit</b>: { NUMBER($timeout_seconds, useGrouping: 0) } s
    *[0] { empty }
    }
    • <b>Error type</b>: <code>{ $timeout_type }</code>
    </blockquote>

    .remnawave-version =
    #RemnawaveVersionWarningEvent

    <b>⚠️ Event: Possible Remnawave incompatibility!</b>

    <blockquote>
    Panel version <b>{ $panel_version }</b> is newer than the tested version <b>{ $max_version }</b>. Some bot features may not work correctly.
    </blockquote>

    { frg-build-info }

    .remnawave =
    #RemnawaveErrorEvent

    <b>🔅 Event: Could not connect to Remnawave!</b>

    <blockquote>
    The bot cannot function correctly without an active connection!
    </blockquote>

    { frg-build-info }

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .webhook =
    #ErrorEvent

    <b>🔅 Event: Webhook error detected!</b>

    { hdr-error }
    <blockquote>
    { $error }
    </blockquote>

    .channel-check =
    #ChannelCheckErrorEvent

    <b>⚠️ Event: Channel/group membership check failed!</b>

    { hdr-user }
    { frg-user-info }

    <blockquote>
    • <b>Reason</b>: <code>{ $reason }</code>
    </blockquote>

    Make sure the bot is a channel/group administrator with permission to view members.

    .notification =
    #NotificationErrorEvent

    <b>⚠️ Event: System notification delivery failed!</b>

    <blockquote>
    • <b>Route</b>: { NUMBER($chat_id, useGrouping: 0) }{ $thread_id ->
        [0] { space }
        *[HAS] :{ NUMBER($thread_id, useGrouping: 0) }
    }
    • <b>Reason</b>: <code>{ $reason }</code>
    </blockquote>

    Check the notification route and make sure the bot is a member of the group with permission to send messages.


event-bot =
    .startup =
    #BotStartupEvent

    <b>🔅 Event: Bot started!</b>

    { frg-build-info }

    <b>🔓 Access</b>:
    <blockquote>
    • <b>Mode</b>: { access-mode }
    • <b>Payments</b>: { $payments_allowed ->
    [0] disabled
    *[1] enabled
    }
    • <b>Registration</b>: { $registration_allowed ->
    [0] disabled
    *[1] enabled
    }
    </blockquote>

    .inline-mode-disabled =
    #BotInlineModeDisabledEvent

    <b>⚠️ Event: Inline mode is disabled in BotFather!</b>

    <blockquote>
    The bot is not configured for inline mode. Some bot features may not work correctly.

    Enable Inline Mode in BotFather: <b>@BotFather → /mybots → Bot Settings → Inline Mode → Enable</b>
    </blockquote>

    .shutdown =
    #BotShutdownEvent

    <b>🔅 Event: Bot stopped!</b>

    { frg-build-info }

    <blockquote>
    • <b>Uptime</b>: { $uptime }
    </blockquote>

    .update =
    #BotUpdateEvent

    <b>🔅 Event: Remnashop update available!</b>

    <b>📑 Versions</b>:
    <blockquote>
    • <b>Current</b>: { $local_version }
    • <b>Latest</b>: { $remote_version }
    </blockquote>


event-user =
    .registered =
    #UserRegisteredEvent

    <b>🔅 Event: New user!</b>

    { hdr-user }
    { frg-user-info }

    { $referrer_user_id ->
    [0] { empty }
    *[HAS]
    <b>🤝 Inviter</b>:
    <blockquote>
    { $referrer_telegram_id ->
        [0] • <b>Email</b>: <code>{ $referrer_email }</code>
        *[HAS] • <b>ID</b>: <code>{ NUMBER($referrer_telegram_id, useGrouping: 0) }</code>
    }
    • <b>Name</b>: { $referrer_name } { $referrer_username ->
        [0] { empty }
        *[HAS] (<a href="tg://user?id={ $referrer_telegram_id }">@{ $referrer_username }</a>)
    }
    </blockquote>
    }

    { $ad_link_id ->
    [0] { empty }
    *[HAS]
    <b>🎯 Advertising link</b>:
    <blockquote>
    • <b>Name</b>: { $ad_link_name }
    • <b>Code</b>: <code>{ $ad_link_code }</code>
    </blockquote>
    }

    .first-connected =
    #UserFirstConnectionEvent

    <b>🔅 Event: User's first connection!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-subscription }
    { frg-subscription-details }

    .device-added =
    #UserDeviceAddedEvent

    <b>🔅 Event: User added a new device!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-hwid }
    { frg-user-hwid }

    .device-deleted =
    #UserDeviceDeletedEvent

    <b>🔅 Event: User removed a device!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-hwid }
    { frg-user-hwid }


event-blacklist =
    .registration-attempt =
    #BlacklistRegistrationAttemptEvent

    <b>🔅 Event: Registration attempt from a blocklisted user!</b>

    { hdr-user }
    { frg-user-info }


event-subscription =
    .trial =
    #SubscriptionTrialEvent

    <b>🔅 Event: Trial subscription activated!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .new =
    #SubscriptionNewEvent

    <b>🔅 Event: Subscription purchased!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .renew =
    #SubscriptionRenewEvent

    <b>🔅 Event: Subscription renewed!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot }

    .change =
    #SubscriptionChangeEvent

    <b>🔅 Event: Subscription changed!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    { hdr-plan }
    { frg-plan-snapshot-comparison }

    .expiring =
    { $is_trial ->
    [0]
    <b>⚠️ Attention! Your subscription expires in { unit-day }.</b>

    Renew it in advance to keep your access to the service!
    *[1]
    <b>⚠️ Attention! Your free trial expires in { unit-day }.</b>

    Get a subscription to keep your access to the service!
    }

    .expired =
    <b>⛔ Attention! Access suspended — VPN is not working.</b>

    { $is_trial ->
    [0] Your subscription has expired. Renew it to continue using the VPN!
    *[1] Your free trial has ended. Get a subscription to continue using the service!
    }

    .expired-ago =
    <b>⛔ Attention! Access suspended — VPN is not working.</b>

    { $is_trial ->
    [0] Your subscription expired { unit-day } ago. Renew it to continue using the service!
    *[1] Your free trial ended { unit-day } ago. Get a subscription to continue using the service!
    }

    .limited =
    <b>⛔ Attention! Access suspended — VPN is not working.</b>

    You have used all your traffic. { $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Renew your subscription to reset traffic and continue using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also renew your subscription to reset traffic.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Get a subscription to continue using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also get a subscription to use the service without restrictions.
        }
    }

    .not-connected =
    <b>🔌 Having trouble connecting?</b>

    If you are having trouble setting up the VPN, we are here to help! Contact support and we will work through it together.

    .revoked =
    #SubscriptionRevokedEvent

    <b>🔅 Event: User reissued their subscription!</b>

    { hdr-user }
    { frg-user-info }

    { hdr-subscription }
    { frg-subscription-details }


event-node =
    .connection-lost =
    #NodeConnectionLostEvent

    <b>🔅 Event: Connection to node lost!</b>

    { hdr-node }
    { frg-node-info }

    .connection-restored =
    #NodeConnectionRestoredEvent

    <b>🔅 Event: Connection to node restored!</b>

    { hdr-node }
    { frg-node-info }

    .traffic-reached =
    #NodeTrafficReachedEvent

    <b>🔅 Event: Node reached the traffic limit threshold!</b>

    { hdr-node }
    { frg-node-info }


event-torrent-blocker =
    .user-blocked =
    <b>⛔ Server access is temporarily restricted.</b>

    BitTorrent traffic was detected on node <b>{ $node_name }</b>.
    The restriction will remain in effect for <b>{ $block_duration }</b>.

    If you need help setting up your connection, contact support.

    .report =
    #TorrentBlockedEvent

    <b>⚠️ Event: BitTorrent traffic detected!</b>

    { hdr-user }
    { frg-user-info }

    <blockquote>
    • <b>Node</b>: { $node_name }
    • <b>IP</b>: <code>{ $blocked_ip }</code>
    • <b>Block duration</b>: { $block_duration }
    • <b>Unblock at</b>: { $will_unblock_at }
    • <b>Protocol</b>: <code>{ $protocol }</code>
    • <b>Source</b>: <code>{ $source }</code>
    • <b>Destination</b>: <code>{ $destination }</code>
    </blockquote>


event-referral =
    .attached =
    <b>🎉 You invited a friend!</b>

    <blockquote>
    User <b>{ $name }</b> joined using your invite link! Reward terms are available in the “Invite” section.
    </blockquote>

    .reward =
    <b>💰 You received a reward!</b>

    <blockquote>
    User <b>{ $name }</b> made a payment. You received { $reward_type ->
    [POINTS] <b>{ $value } { $value ->
        [one] point
        [few] points
        *[more] points
        }</b>

    <i>To use your points, open the “Invite” section in the bot to learn about available rewards and how to use them.</i>
    [EXTRA_DAYS] <b>{ $value } extra { $value ->
        [one] day
        [few] days
        *[more] days
        }</b> added to your subscription!
    *[OTHER] <b>{ $value } { $reward_type }</b>
    }
    </blockquote>

    .reward-failed =
    <b>❌ Could not grant your reward!</b>

    <blockquote>
    User <b>{ $name }</b> made a payment, but we could not grant your reward because <b>you do not have a paid subscription</b> to which we could add { $value } { $reward_type ->
    [POINTS] { $value ->
        [one] point
        [few] points
        *[more] points
        }
    [EXTRA_DAYS] extra { $value ->
        [one] day
        [few] days
        *[more] days
        }
    *[OTHER] { $reward_type }
    }.

    <i>Buy a subscription to earn bonuses for inviting friends!</i>
    </blockquote>

    .invitation-reward =
    <b>🎁 You received an invitation reward!</b>

    <blockquote>
    User <b>{ $name }</b> registered using your link. You received <b>{ $value } { $reward_type ->
    [POINTS] { $value ->
        [one] point
        [few] points
        *[more] points
        }
    [EXTRA_DAYS] extra { $value ->
        [one] day
        [few] days
        *[more] days
        }
    *[OTHER] { $reward_type }
    }</b>{ $reward_type ->
    [EXTRA_DAYS] { space }added to your subscription!
    *[OTHER] !
    }
    </blockquote>

    .invitation-reward-failed =
    <b>❌ Could not grant your invitation reward!</b>

    <blockquote>
    User <b>{ $name }</b> registered using your link, but we could not grant the reward: <b>you do not have a subscription</b> to which we could add bonus days.

    <i>Activate a trial or paid subscription to earn days for invitations.</i>
    </blockquote>

event-promocode =
    .activated =
    #PromocodeActivatedEvent

    <b>🔅 Event: Promo code redeemed!</b>

    { hdr-user }
    { frg-user-info }

    <b>🎟 Promo code</b>:
    <blockquote>
    • <b>Code</b>: <code>{ $promocode_code }</code>
    • <b>Type</b>: { promocode-type }
    • <b>Reward</b>: { frg-promocode-reward }
    </blockquote>

event-payment =
    .refunded =
    #PaymentRefundedEvent

    <b>⚠️ Event: Payment refunded!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Manual review required — the user's subscription may still be active.

    .referral-failed =
    <b>⚠️ Could not grant the referral reward</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    The purchase completed successfully, but an error occurred while granting the referral reward. Manual review required.

    .purchase-failed =
    <b>⚠️ Event: Payment processing failed!</b>

    { hdr-payment }
    { frg-payment-info }

    { hdr-user }
    { frg-user-info }

    Payment received, but the subscription could not be granted. The transaction is marked as FAILED. Manual review required.

event-earning-task-completed =
    #TaskCompletedEvent

    <b>✅ Event: Task completed!</b>

    { hdr-user }
    { frg-user-info }

    <b>📣 Completed task</b>:
    <blockquote>
    • <b>Channel</b>: <a href="{ $channel_url }">{ $channel_title }</a>
    • <b>Channel ID</b>: <code>{ $channel_id }</code>
    </blockquote>

    <b>🎁 Reward</b>:
    <blockquote>
    { $days ->
        [0] { empty }
        *[HAS] • <b>Subscription days</b>: +{ NUMBER($days, useGrouping: 0) }
        • <b>Subscription expiry</b>: { $expire_before } → { $expire_after }
    }
    { $plan_changed ->
        [1] • <b>Plan</b>: { $plan_before } → { $plan_after }
        *[0] { empty }
    }
    { $kind_changed ->
        [1] • <b>Subscription type</b>: { $kind_before } → { $kind_after }
        *[0] { empty }
    }
    { $traffic_limit_changed ->
        [1] • <b>Traffic limit</b>: { $traffic_limit_before } → { $traffic_limit_after }
        *[0] { empty }
    }
    { $device_limit_changed ->
        [1] • <b>Device limit</b>: { $device_limit_before } → { $device_limit_after }
        *[0] { empty }
    }
    { $reset_traffic ->
        [1] • <b>Traffic reset</b>: { $traffic_before } → { $traffic_after }
        *[0] { empty }
    }
    { $discount ->
        [0] { empty }
        *[HAS] • <b>Next purchase discount</b>: { NUMBER($discount_before, useGrouping: 0) }% → { NUMBER($discount_after, useGrouping: 0) }%
    }
    </blockquote>

earning-event-unknown = No data
earning-event-no-subscription = No subscription
earning-event-trial = Trial
earning-event-regular = Regular

event-remnashop-welcome =
    <b>💎 Meow VPN (ToBeVPN) v{ $version }</b>

    A VPN service covering everything from our own apps for multiple platforms to simple subscription configurations for your preferred clients.

    ⭐ <i>Star us on <a href="{ $repository }">GitHub</a> and join our <a href="https://t.me/@alstrive">community</a>.</i>
