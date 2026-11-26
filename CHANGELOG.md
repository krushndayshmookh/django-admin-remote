# Changelog

All notable changes to this project are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## 0.2.0 - 2026-11-26

### Added

- File uploads. `AdminForm.file_fields`, `has_file()` and `set_file(name, filename, content, content_type)` attach a file to a file input, and `add_row` takes `(filename, content[, content_type])` for an inline file input. A form with an attached file is submitted as `multipart/form-data`.
- `AdminClient.post()` and `request()` take `files=` (passed to `requests`); a redirect after the POST is followed with a plain GET.

### Changed

- A file input with nothing attached is still left out of the POST (keeps the stored file), as before.

## 0.1.0 - 2026-11-11

First release.

### Added

- `AdminClient`: polite `requests` based client with a delay between requests, manual redirect following, GET retries on 5xx, no POST retries, and a same-host rule.
- Authentication from existing cookies (cookie dict, cookie jar or a Playwright `storage_state`) and `AdminClient.login()` for the standard admin login form.
- `AdminClient.changelist()`: iterate over the ids of a change list across all pages, with filters and a limit. Works with both 0-based and 1-based `?p=` page numbers.
- `AdminClient.read()` and `parse_change_form()`: editable fields, read-only fields with the stored value recovered, boolean icons, links, split date and time widgets, inline formset rows.
- `AdminForm`: load an add or change page and submit it like a browser, including select values by label, inline row add and delete, and custom submit buttons.
- `parse_changelist()` and `parse_admin_datetime()`.
- Exceptions `NotLoggedIn`, `FormError`, `AdminHTTPError` with the common base `AdminError`.
