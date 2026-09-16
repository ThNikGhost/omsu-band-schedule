//! Logging into the AstroBox console.
//!
//! The upstream template also wires up `tracing-appender` for rolling log
//! files, but that crate pulls in `symlink`, which has no wasm32-wasip2
//! support and fails to compile. Dropping it costs nothing: a plugin has one
//! writable directory and the host already shows everything written here.

use std::io::{self, Write};

use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt};

pub fn init() {
    let writer = move || PluginWriter(io::stdout());
    let console_layer = fmt::layer()
        .with_target(true)
        .with_ansi(false)
        .with_file(true)
        .with_line_number(true)
        .with_writer(writer)
        .compact();

    tracing_subscriber::registry().with(console_layer).init();
}

/// Prefixes every line so plugin output is distinguishable in the host log.
struct PluginWriter<W: Write>(W);

impl<W: Write> Write for PluginWriter<W> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0.write_all(b"[omsu-schedule] ")?;
        self.0.write(buf)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.0.flush()
    }
}
