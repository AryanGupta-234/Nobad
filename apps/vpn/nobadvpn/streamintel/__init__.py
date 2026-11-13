"""Streaming Region Intelligence: where a title is listed, under which platforms and offer types, documented
country restrictions, and which of the user's own VPN servers match those catalogues.

Independent of the VPN engine: it only *reads* engine state (servers, geolocation, latency, service history) and
leaves connecting to the existing `connect` API. Data sources and their limits are documented in
docs/STREAMING-INTELLIGENCE.md."""
