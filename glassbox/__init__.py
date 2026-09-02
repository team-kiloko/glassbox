"""GlassBox — a governed, auditable options trading agent.

Package root. Deliberately empty of logic: modules are imported explicitly
(``from glassbox.screener import screen_chain``) so that importing the package
never pulls in a network client, a config file, or a clock.
"""
