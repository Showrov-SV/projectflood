"""Flood Monitoring & Prediction System - application package.

Layers (a module only imports from the ones above it):
  config, geography, mail_roles, alert_sound   settings & static data
  database, auth                               storage & login
  prediction, datasets, messaging, alerts,
  sensors                                      business logic
  maps, alert_ui, mail_ui, prediction_ui,
  data_ui, sidebar                             reusable screens
  dashboard_*                                  one file per dashboard
"""
