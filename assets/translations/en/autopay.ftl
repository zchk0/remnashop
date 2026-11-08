btn-autopay-settings = 🔄 Auto-payment settings
btn-autopay-enable = ✅ Enable for my plan
btn-autopay-disable = ⛔ Disable auto-payment
btn-autopay-refresh = 🔄 Check status
btn-autopay-bind = 🏦 Confirm account linking with your bank
btn-autopay-create = ✅ Set up auto-payment
btn-autopay-email = { $has_email ->
    [1] ✉️ Change email
    *[0] ✉️ Add email
    }
autopay-email-not-set = Not specified
btn-gateway-autopay-toggle = { $enabled ->
    [1] 🟢 Auto-payments enabled
    *[0] 🔴 Auto-payments disabled
    }

autopay-status-disabled = Disabled
autopay-status-pending = Awaiting bank confirmation
autopay-status-active = Enabled
autopay-status-pastdue = Payment failed — check your bank account
autopay-status-cancelled = Disabled
autopay-status-failed = Account not linked

msg-autopay-settings =
    <b>🔄 Auto-payment settings</b>

    • Status: <b>{ $ap_status }</b>
    • Plan: <b>{ $ap_plan_name }</b>
    • Payment amount: <b>{ $ap_amount } ₽</b>
    • Next payment: <b>{ $ap_next_charge }</b>
    • Email: <code>{ $ap_email }</code>

    If confirmation is pending, open the link and confirm account linking with your bank within 30 minutes.
    Disabling auto-payment stops future charges. Your paid subscription time is retained.

msg-autopay-confirm =
    <b>🔄 Set up SBP auto-payment</b>

    • Plan: <b>{ $ap_plan_name }</b>
    • Recurring payment: <b>{ $ap_amount } ₽</b>
    • Billing period: <b>{ $ap_period }</b>

    Once account linking is confirmed, Platega will automatically charge this amount each billing period. The first charge may occur immediately; the paid period will be added to the remaining time on the same plan.
    One-time purchase discounts do not apply to recurring payments. The amount is fixed when auto-payment is set up.
    You can stop future charges in the auto-payment settings.

msg-autopay-email =
    <b>✉️ Auto-payment email</b>

    An email address is optional when setting up auto-payment in the bot. The address will be saved in your subscription profile.

    Send your email address.

msg-autopay-refresh-error =
    ⚠️ Could not retrieve the current Platega status. Saved data is shown above. Try checking the status again.

ntf-autopay-unavailable = Auto-payment is unavailable for this plan or billing period.
ntf-autopay-disabled = Auto-payment setup is currently disabled. You can manage an existing auto-payment in its settings.
ntf-autopay-invalid-email = Enter a valid email address.
ntf-autopay-create-error = Could not set up auto-payment. If it is already enabled or awaiting account linking, open its settings. To change plans, disable the existing auto-payment first.
ntf-autopay-cancel-error = Platega did not confirm that auto-payment was disabled. Try again; auto-payment may still be active.
ntf-autopay-cancelled = Auto-payment disabled. Your paid subscription time is retained.
ntf-autopay-paid = ✅ SBP auto-payment successful. Your subscription has been renewed.
ntf-autopay-failed = ⚠️ SBP auto-payment or account linking failed. Check your bank account and the status under “Subscription → Auto-payment settings”. Your paid subscription time is retained.
ntf-autopay-reset-review = ⚠️ Auto-payment { $payment_id }, user { $user_id }: the traffic reset result in the panel is unknown. Check traffic manually; a repeated automatic reset was skipped.
