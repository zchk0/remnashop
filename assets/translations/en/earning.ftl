btn-earning =
    .admin = 🎁 Earn free days
    .advertise = 📣 Advertise your channel
    .open-channel = 📢 Open channel
    .check = ✅ Check membership
    .enabled = Section enabled: { $enabled_label }
    .audience = 👥 Access
    .create = ➕ Add channel
    .channels = 📢 Channels
    .active = Task active: { $active_label }
    .reset = Traffic reset: { $reset_label }
    .save = 💾 Save
    .delete = 🗑 Delete
    .reset-completions = 🔄 Reset completions
    .pending = ⏳ Pending rewards
    .retry = 🔄 Retry reward delivery
    .confirm-reset = ✅ Traffic reset done — finish delivery
btn-earning-edit-channel = 📢 Channel
btn-earning-edit-title = ✏️ Title
btn-earning-edit-days = 🗓 Free days
btn-earning-edit-discount = 🏷 Purchase discount
btn-earning-edit-max-claims = 👥 Completion limit
btn-earning-edit-plan-id = 📦 Plan for users without a subscription
btn-earning-edit-trial-plan-id = 🔄 Trial replacement plan
btn-earning-edit-trial-days = 🗓 Days for trial replacement
btn-earning-edit-allowed-telegram-ids = 👤 Users
btn-earning-edit-button-text = ✏️ Button text
btn-earning-edit-subscriber-price = 💰 Price per subscriber

earning-yes = Yes
earning-no = No
earning-unset = Not selected
earning-audience-all = All users
earning-audience-admins = Administrators only
earning-audience-selected = Selected users
earning-reward-days = +{ NUMBER($days, useGrouping: 0) } { $days ->
    [one] day
    [few] days
    *[OTHER] days
    }
earning-reward-reset = Reset used traffic
earning-reward-discount = { $discount }% off your next purchase
earning-advertise-request = Hello! I would like to advertise my channel in the “Earn free days” section.

msg-earning-main =
    <b>Earn free days 🎁</b>

    Choose a channel, check the reward, and join it. Then return to the bot and tap “Check membership” — you will receive your reward once your membership is confirmed.

    Each task can be completed once.
msg-earning-empty =
    <blockquote>No tasks are available right now. Check back later!</blockquote>
msg-earning-available-tasks =
    <blockquote>Available tasks: <b>{ NUMBER($available_tasks_count, useGrouping: 0) }</b></blockquote>
msg-earning-task =
    <b>📢 { $title }</b>

    🎁 Reward:
    { $reward }

    <i>Join the channel and tap the check button. If you are already a member, you can check your membership right away.</i>
msg-earning-advertise =
    <b>📣 Advertise your channel</b>

    Your channel will appear in the tasks, and users will receive a reward for joining.

    💰 Price per subscriber: { $price }
    👥 Minimum order: 15 subscribers.

    The bot checks channel membership when a task is completed.

    Contact support to arrange placement.
msg-earning-admin =
    <b>🎁 Earn free days — settings</b>

    <blockquote>
    • <b>Section enabled:</b> { $enabled_label }
    • <b>Access:</b> { $audience_label }
    • <b>Selected IDs:</b> { $selected_ids }
    • <b>Button:</b> { $button_text }
    • <b>Price per subscriber:</b> { $price }
    </blockquote>

    <i>The button appears only when the user has access and tasks are available.</i>
msg-earning-channels =
    <b>📢 Channels</b>

    <b>Task completions:</b>
    <blockquote>
    • <b>Today:</b> { $completed_daily }
    • <b>This week:</b> { $completed_weekly }
    • <b>This month:</b> { $completed_monthly }
    • <b>Total:</b> { $completed_total }
    </blockquote>

    🟢 Active tasks: { $active_tasks }
    ✅ Completed tasks: { $completed_tasks }

    <b>Before adding a channel</b>
    Add the bot as a channel administrator. Administrator status with the basic channel management permission (can_manage_chat) is enough to check membership.
    • <b>Public channel:</b> @username or link.
    • <b>Private channel:</b> numeric ID and invite link, separated by a space.
msg-earning-admin-task =
    <b>📢 { $title }</b>

    <blockquote>
    • <b>Channel ID:</b> <code>{ $channel_id }</code>
    • <b>Link:</b> { $channel_url }
    • <b>Active:</b> { $active_label }
    • <b>Reward:</b> { $reward }
    • <b>Completions and reserved spots:</b> { $claims_count } / { $max_claims }
    • <b>Plan for users without a subscription:</b> { $plan_name }
    • <b>Trial replacement plan:</b> { $trial_plan_name }
    • <b>Days for trial replacement:</b> { $trial_days }
    </blockquote>

    <b>Statistics:</b>
    <blockquote>
    • <b>Today:</b> { $completed_daily }
    • <b>This week:</b> { $completed_weekly }
    • <b>This month:</b> { $completed_monthly }
    • <b>Total:</b> { $completed_total }
    </blockquote>

    <i>If no trial replacement plan is selected, days will be added to the current trial subscription. If a plan is selected, it will replace the trial with the specified number of days.
    Users without a subscription will see tasks that award days or a traffic reset only if a plan is selected and the reward includes days.</i>

msg-earning-audience =
    <b>Who can access this section?</b>
    For “Selected users” mode, specify a list of Telegram IDs.
msg-earning-plans =
    Choose a regular plan. Its limits and groups will be applied when a subscription is granted. Trial plans cannot be used to replace a trial subscription.
    “Not selected” disables granting a new subscription or replacing a trial.
msg-earning-delete =
    Delete the task “{ $title }”? Completion history will be retained. Users can still receive reserved rewards by checking their membership again.
msg-earning-reset-completions =
    <b>🔄 Reset completions</b>

    Reset completed claims for the task “{ $title }” for all users?

    Users will be able to complete the task and receive the reward again. Completed claims will be removed from the statistics, and the spots they occupied will become available.

    Rewards already granted will be retained. Pending deliveries will not be deleted and can be completed using the saved reward.
msg-earning-pending =
    <b>⏳ Pending rewards</b>
    Reserved rewards whose delivery has not been completed are shown here. Retrying delivery uses the saved reward.
msg-earning-claim =
    <b>Reward for task #{ $claim_task_id }</b>
    User ID in the database: { $claim_user_id }

    Days: { $claim_days }
    Discount: { $claim_discount }%
    Traffic reset: { $claim_reset }
    Subscription updated: { $claim_subscription_done }
    Panel ID: <code>{ $claim_panel_id }</code>
    Saved subscription expiry: { $claim_expire }

    If the traffic reset response was lost, check the traffic in the panel. If necessary, reset it manually, then tap “Traffic reset done — finish delivery”. The bot will stop sending reset requests and complete the remaining rewards.

msg-earning-input-channel =
    <b>Add the bot as a channel administrator.</b>
    The basic management permission (can_manage_chat) is enough; permission to post or delete messages is not required.

    Send @username or https://t.me/username.
    For a private channel: -1001234567890 https://t.me/+INVITE
    The bot will check access. You cannot change the ID of a channel with task completions — create a new task instead.
msg-earning-input-title = Send the task title (up to 128 characters).
msg-earning-input-days = Send the number of free days from 0 to 3650. 0 means no reward in days.
msg-earning-input-discount = Send the discount for the next purchase from 0 to 100%. 0 means no discount. Discounts do not stack; the higher one is retained.
msg-earning-input-max-claims = Send the maximum number of completions. 0 means unlimited. Granted and reserved rewards count toward the limit.
msg-earning-input-trial-days = Send the number of days from 1 to 3650 for the trial replacement plan. 0 means use the regular reward in days.
msg-earning-input-allowed-telegram-ids = Send users' Telegram IDs separated by spaces, commas, or new lines. 0 clears the list.
msg-earning-input-button-text = Send the main menu button text (1 to 64 characters).
msg-earning-input-subscriber-price = Send the price per subscriber with its currency, for example: 10 ₽. This price is shown in the placement information. Minimum order: 15 subscribers.

ntf-earning =
    .unavailable = Task unavailable.
    .full = All spots are taken. Choose another channel.
    .already-claimed = You have already received the reward for this task.
    .not-subscribed = Channel membership not found. Join the channel and check again. Your join request must be approved.
    .subscription-required = This reward requires a subscription. Choose another task or contact support.
    .plan-unavailable = The reward plan is unavailable. Contact support.
    .finish-pending = First finish claiming the reward for the previous task by checking your channel membership again.
    .review-required = Your reward has been saved, but support needs to review it. Contact us; the reward does not need to be granted again.
    .telegram-error = Could not check channel membership. Try again later or contact support about the bot's access to the channel.
    .retry = Could not complete reward delivery. Your spot and reward have been saved: check again later.
    .success = 🎉 Channel membership confirmed! Reward granted.
    .channel-admin-required = Could not add the channel. Check the ID, link, and bot status: the bot must be a channel administrator. For a private channel, provide its ID and invite link separated by a space.
    .invalid-task = Check the channel, reward, limit, and plans. An active task requires a channel the bot can access and at least one reward. A channel with task completions cannot be replaced with another one.
    .saved = Saved
    .completions-reset = ✅ Completed claims have been reset. The task can be completed again.
