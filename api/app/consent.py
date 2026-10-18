"""Consent wording shown on the registration form.

The form fetches this from GET /form-config and sends back `consent_version`.
Whenever the wording changes, bump CONSENT_VERSION in .env too, so registrations
record exactly which text each student agreed to. Have the organisers approve it.
"""

CONSENT_ENTRY = (
    "I agree that Moksha (NSUT) may use the details and ID card photo I submit to verify that I am "
    "a college student and to manage my entry to Moksha. This data is deleted 30 days after the fest."
)

CONSENT_DATASET = (
    "Optional: I also agree that my ID card photo and details may be used to improve this verification "
    "system, which may be developed into a product. This is not required to attend. I can withdraw at "
    "any time by emailing the organisers, and my data will then be deleted."
)
