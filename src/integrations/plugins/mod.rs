//! Platform-selected native plugin implementation and the fallback without native plugins (the
//! plugin ABI is x86-64 "win64": native.rs runs on x86-64 Windows and Linux; the browser,
//! Android, macOS and ARM64 take web.rs: the built-in effects and codecs only).
#[cfg(all(target_arch = "x86_64", any(windows, target_os = "linux")))]
mod native;
#[cfg(not(all(target_arch = "x86_64", any(windows, target_os = "linux"))))]
mod web;

#[cfg(all(target_arch = "x86_64", any(windows, target_os = "linux")))]
pub(crate) use native::*;
#[cfg(not(all(target_arch = "x86_64", any(windows, target_os = "linux"))))]
pub(crate) use web::*;
