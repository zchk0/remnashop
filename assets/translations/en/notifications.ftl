ntf-error =
    .unknown = ⚠️ <i>An error occurred.</i>
    .permission-denied = ⚠️ <i>You do not have sufficient permissions.</i>
    .remnawave-unavailable = ⚠️ <i>The subscription service is temporarily unavailable. Try again in a few seconds.</i>
    .log-not-found = ⚠️ <i>Log file not found.</i>
    .logs-disabled = ⚠️ <i>File logging is disabled.</i>

    .lost-context = ⚠️ <i>This screen is outdated. Open the menu with /start.</i>
    .lost-context-restart = ⚠️ <i>This screen is outdated. The dialog has been restarted.</i>

ntf-common =
    .trial-unavailable = ⚠️ <i>The trial subscription is temporarily unavailable.</i>
    .throttling = ⚠️ <i>You are sending too many requests. Please wait.</i>
    .double-click-confirm = ⚠️ <i>Tap again to confirm the action.</i>
    .squads-empty = ⚠️ <i>No squads found. Check that they exist in the panel.</i>

    .withdraw-points = ❌ <i>You do not have enough points to exchange.</i>
    .internal-squads-empty = ❌ <i>Select at least one internal squad.</i>

    .invalid-value = ❌ <i>Invalid value.</i>
    .value-updated = ✅ <i>Setting updated successfully.</i>
    .cooldown-active = ⏳ <i>Temporarily unavailable. Try again in { $available_at }.</i>

    .plan-not-found = ❌ <i>Plan not found or unavailable.</i>
    .connect-not-available =
    ⚠️ { $status ->
    [LIMITED]
    You have used all your available traffic. { $is_trial ->
    [0] { $traffic_strategy ->
        [NO_RESET] Renew your subscription to reset traffic and continue using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also renew your subscription to reset traffic.
        }
    *[1] { $traffic_strategy ->
        [NO_RESET] Get a subscription to continue using the service!
        *[RESET] Traffic will be restored in { $reset_time }. You can also get a subscription to use the service without restrictions.
        }
    }
    [EXPIRED]
    { $is_trial ->
    [0] Your subscription has expired. Renew it or purchase a new one.
    *[1] Your free trial has ended. Get a subscription to continue using the service.
    }
    *[OTHER] An error occurred while checking the status, or the subscription was disabled. Contact support.
    }

ntf-command =
    .paysupport = 💸 <b>To request a refund, contact support.</b>
    .rules = ⚠️ <b>Please read the <a href="{ $url }">Terms of Service</a> before using the service.</b>
    .help = 🆘 <b>Tap the button below to contact support.</b>

ntf-requirement =
    .channel-join-required = ❇️ Join our channel for <b>free days, promotions, and news</b>. Once you have joined, tap “Confirm”.
    .channel-join-required-left = ⚠️ You left the channel. Join it to continue using the bot.
    .rules-accept-required = ⚠️ <b>Before using the service, read and accept the <a href="{ $url }">Terms of Service</a>.</b>
    .channel-join-error = ⚠️ We could not confirm your channel membership. Check that you have joined and try again.
    .trial-paused = ⚠️ Your trial has been paused because you left the channel. Join again to restore access.
    .trial-restored = ✅ Your trial has resumed.

ntf-user =
    .not-found = <i>❌ User not found.</i>
    .transaction-not-found = ❌ <i>Transaction not found.</i>
    .transactions-empty = ❌ <i>The transaction list is empty.</i>
    .payment-recheck-started = Checking payment status…
    .payment-recheck-success = ✅ <i>Payment confirmed by the payment provider. The purchase has been processed and the subscription granted.</i>
    .payment-recheck-already-processed = ✅ <i>Payment confirmed by the payment provider and already accepted by the bot. The purchase was not applied again.</i>
    .payment-recheck-refunded = ⚠️ <i>The payment is marked as refunded in the bot. The purchase was not applied again.</i>
    .payment-recheck-unpaid = ℹ️ <i>The payment provider has not confirmed payment. Status: <code>{ $status }</code>. The purchase was not applied.</i>
    .payment-recheck-error = ❌ <i>Could not check payment with the payment provider, or payment details did not match. The purchase was not applied. Try again later.</i>
    .payment-recheck-purchase-failed = ⚠️ <i>Payment confirmed, but the purchase could not be fully processed. Check the user's subscription and the error log.</i>
    .subscription-empty = ❌ <i>No active subscription found.</i>
    .subscription-deleted = ✅ <i>Subscription deleted successfully.</i>
    .plans-empty = ❌ <i>No plans available.</i>
    .devices-empty = ❌ <i>The device list is empty.</i>
    .allowed-plans-empty = ❌ <i>No plans available for granting access.</i>
    .referral-reset = ✅ <i>Referral link reset successfully.</i>
    .message-success = ✅ <i>Message sent successfully.</i>
    .message-failed = ❌ <i>Could not send the message.</i>

    .sync-already = ✅ <i>Subscription details are identical.</i>
    .sync-missing-data = ⚠️ <i>Cannot synchronize. Subscription details are missing from both the panel and the bot.</i>
    .sync-success = ✅ <i>Subscription synchronized.</i>

    .invalid-expire-time = ❌ <i>Cannot { $operation ->
    [ADD] extend
    *[SUB] shorten
    } the subscription by the specified number of days.</i>

    .invalid-points = ❌ <i>Cannot { $operation ->
    [ADD] add
    *[SUB] deduct
    } the specified number of points.</i>

ntf-access =
    .maintenance = 🚧 <i>The bot is under maintenance. Try again later.</i>
    .registration-disabled = ❌ <i>New user registration is disabled.</i>
    .registration-invite-only = ❌ <i>Registration is by invitation only.</i>
    .payments-disabled = 🚧 <i>Payments are temporarily unavailable! You will be notified when they are restored.</i>
    .payments-restored = ❇️ <i>Payments have been restored! You can now purchase or renew a subscription. Thank you for waiting.</i>

ntf-plan =
    .not-file = ⚠️ <i>Send the plans as a JSON file.</i>
    .import-failed = ❌ <i>Import failed.</i>
    .import-success = ✅ <i>Imported successfully.</i>
    .export-plans-not-selected = ❌ <i>Select at least one plan to export.</i>
    .export-failed = ❌ <i>Export failed.</i>
    .export-success = ✅ <i>Selected plans exported.</i>
    .trial-single-duration = ❌ <i>A trial plan can have only one duration.</i>
    .duration-already-exists = ❌ <i>This duration already exists.</i>
    .name-already-exists = ❌ <i>A plan with this name already exists.</i>
    .user-already-allowed = ❌ <i>This user ID has already been added.</i>

    .updated = ✅ <i>Plan updated successfully.</i>
    .created = ✅ <i>Plan created successfully.</i>
    .deleted = ✅ <i>Plan deleted successfully.</i>

ntf-gateway =
    .not-configured = ❌ <i>The payment gateway is not configured.</i>
    .not-configurable = ❌ <i>The payment gateway has no settings.</i>
    .test-payment-created = ✅ <i><a href="{ $url }">Test payment</a> created successfully.</i>
    .test-payment-error = ❌ <i>Could not create the test payment.</i>
    .test-payment-confirmed = ✅ <i>Test payment processed successfully.</i>
    .field-reset = ✅ <i>Field value cleared.</i>
    .field-reset-deactivated = ✅ <i>Field value cleared. The gateway has been disabled because required settings are missing.</i>

ntf-subscription =
    .plans-unavailable = ❌ <i>No plans are currently available.</i>
    .gateways-unavailable = ❌ <i>No payment methods are currently available.</i>
    .renew-plan-unavailable = ❌ <i>The current plan is outdated and cannot be renewed.</i>
    .payment-creation-failed = ❌ <i>Could not create the payment. Try again later.</i>

ntf-broadcast =
    .text-too-long = ❌ Maximum character count exceeded ({ $max_limit }).
    .list-empty = ❌ <i>The broadcast list is empty.</i>
    .plans-unavailable = ❌ <i>No plans available.</i>
    .audience-unavailable = ❌ <i>No users in the selected audience.</i>
    .source-unavailable = ❌ <i>The original broadcast is no longer available. Choose another broadcast.</i>
    .content-empty = ❌ <i>Content is empty.</i>
    .content-saved = ✅ <i>Content saved successfully.</i>
    .custom-button-saved = ✅ <i>Custom button settings saved.</i>
    .custom-button-deleted = ✅ <i>Custom button removed from the broadcast.</i>
    .custom-button-text-invalid = ❌ <i>Button text must contain 1 to 64 characters.</i>
    .custom-button-url-invalid = ❌ <i>Send a valid HTTPS link.</i>
    .custom-button-incomplete = ❌ <i>Specify the custom button text and link, or remove the button.</i>
    .excluded-users-saved = ✅ <i>Exclusions saved: { $excluded_count }. Broadcast recipients: { $audience_count }.</i>
    .excluded-users-cleared = ✅ <i>ID and registration time exclusions cleared.</i>
    .excluded-users-invalid = ❌ <i>Send positive Telegram IDs separated by spaces, commas, semicolons, or new lines.</i>
    .excluded-users-too-many = ❌ <i>You can exclude up to 1000 Telegram IDs at a time.</i>

    .not-cancelable = ❌ <i>This broadcast cannot be canceled.</i>
    .canceled = ✅ <i>Broadcast canceled successfully.</i>
    .deleting = ⚠️ <i>Sent messages are being deleted.</i>
    .already-deleted = ❌ <i>The broadcast has already been deleted or is being deleted.</i>

    .deleted-success =
        ℹ️ Deletion results for broadcast <code>{ $task_id }</code>.

        <blockquote>
        • <b>Total messages</b>: { $total_count }
        • <b>Deleted</b>: { $deleted_count }
        • <b>Could not delete</b>: { $failed_count }
        </blockquote>

ntf-importer =
    .not-file = ⚠️ <i>Send the database as a file.</i>
    .db-failed = ❌ <i>Could not export users from the database.</i>
    .users-empty = ❌ <i>The database contains no users.</i>

    .started = ✅ <i>Import started. Wait for it to finish...</i>
    .already-running = ⚠️ <i>An import is already in progress. Please wait.</i>

ntf-sync =
    .from-panel-started = ✅ <i>Panel → bot synchronization started. Wait for it to finish...</i>
    .from-bot-started = ✅ <i>Bot → panel synchronization started. Wait for it to finish...</i>
    .users-not-found = ❌ <i>No users found to synchronize.</i>
    .already-running = ⚠️ <i>Synchronization is already in progress. Please wait.</i>

ntf-menu-editor =
    .button-saved = ✅ <i>Button saved successfully.</i>
    .invalid-payload = ❌ <i>Invalid URL format.</i>

ntf-devices =
    .deleted = ✅ <i>Device deleted.</i>
    .all-deleted = ✅ <i>All devices deleted.</i>
    .reissued = ✅ <i>Subscription reissued successfully.</i>
    .subscription-link-reset =
        ⚠️ <i>Your subscription link was reset after a device was unlinked in ToBeVPN.</i>

        <b>New link:</b>
        <code>{ $subscription_url }</code>

        <i>If you use other clients (Happ, V2rayNG, etc.), add the new link to them.</i>

ntf-backup =
    .assets-started = ⏳ <i>Backing up assets...</i>
    .db-started = ⏳ <i>Backing up the database...</i>
    .error = ❌ <i>Backup failed</i>

ntf-blacklist =
    .list-empty = ❌ <i>The blocklist is empty.</i>
    .no-ids-found = ❌ <i>No IDs found at this link.</i>
    .source-removed = ✅ <i>List deleted.</i>
    .blocked-ids-empty = ❌ <i>The blocked ID list is empty.</i>
    .blocked-ids-cleared = ✅ <i>Cleared { $count } IDs.</i>

    .block-result =
    ℹ️ Blocking results.

    <blockquote>
    • <b>Total IDs</b>: { $total }
    • <b>Users blocked</b>: { $blocked_users }
    • <b>IDs blocked</b>: { $blocked_ids }
    • <b>Already blocked</b>: { $already_blocked }
    </blockquote>

ntf-invite =
    .referral-reset = ✅ <i>Referral link updated.</i>

ntf-promocode =
    .not-found = ❌ <i>Promo code not found or invalid.</i>
    .not-available = ❌ <i>Promo code unavailable.</i>
    .expired = ❌ <i>The promo code has expired.</i>
    .already-activated = ❌ <i>You have already redeemed this promo code.</i>
    .activated = ✅ <i>Promo code redeemed successfully!</i>
    .activation-failed = ❌ <i>Could not redeem the promo code. Try again later.</i>
    .code-exists = ❌ <i>A promo code with this code already exists.</i>
    .created = ✅ <i>Promo code created.</i>
    .deleted = ✅ <i>Promo code deleted.</i>
    .fields-required = ❌ <i>Enter a reward value.</i>
    .invalid-code = ❌ <i>The code may contain only Latin letters, digits, hyphens, and underscores.</i>
    .plans-empty = ❌ <i>No plans available.</i>
    .updated = ✅ <i>Promo code updated.</i>

ntf-flippay-methods-refreshed = ✅ <i>FlipPay payment methods updated.</i>
ntf-flippay-methods-refresh-failed = ❌ <i>Could not retrieve FlipPay payment methods. Check your merchant keys and try again.</i>
ntf-flippay-method-unavailable = ❌ <i>This payment method is currently unavailable. Choose another one.</i>
ntf-rivara-method-unavailable = ❌ <i>This payment method is currently unavailable. Choose another one.</i>

ntf-ad-link =
    .created = ✅ <i>Advertising link created.</i>
    .updated = ✅ <i>Advertising link updated.</i>
    .deleted = ✅ <i>Advertising link deleted.</i>

ntf-language-unavailable = This language is currently unavailable. Choose a language from the list.
