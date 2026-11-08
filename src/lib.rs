//! JFPainter raster editor. See ../docs/ARCHITECTURE.md for module ownership.
#![no_std]
#![deny(unsafe_code)]
#![allow(dead_code)]

use jflib::ui;

extern crate alloc;

mod app;
mod diagnostics;
mod document;
mod effects;
mod integrations;
mod preferences;
mod tools;
mod workspace;

ui::main!(app::run());
