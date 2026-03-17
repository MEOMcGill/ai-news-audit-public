# ==============================================================================
# MEO Theme and Color Palettes for Data Analysis
# Source this file at the top of analysis scripts:
#   source("analysis/meo_theme.R")
# ==============================================================================

library(ggplot2)
library(showtext)

# ------------------------------------------------------------------------------
# Font Setup
# ------------------------------------------------------------------------------

#font_add_google("Poppins", "poppins")
showtext_auto()
showtext_opts(dpi = 300)

# ------------------------------------------------------------------------------
# Themes (Light and Dark)
# ------------------------------------------------------------------------------

theme_meo <- theme_minimal(base_family = "poppins", base_size = 10) +
  theme(
    axis.title.x = element_text(size = 9),
    axis.title.y = element_text(size = 9),
    axis.text.y = element_text(size = 8),
    axis.text.x = element_text(size = 8),
    plot.title = element_text(size = 12, face = "bold", hjust = 0.5),
    plot.subtitle = element_text(size = 10, hjust = 0.5),
    plot.caption = element_text(size = 8, hjust = 1),
    legend.position = "bottom",
    panel.grid.minor.x = element_blank(),
    legend.title = element_blank(),
    legend.text = element_text(size = 9),
    strip.text = element_text(size = 10),
    axis.ticks = element_blank(),
    plot.margin = margin(0.2, 0.8, 0.2, 0.8, "cm")
  )

theme_meo_dark <- theme_minimal(base_family = "poppins", base_size = 10) +
  theme(
    axis.title.x = element_text(size = 9, color = "white"),
    axis.title.y = element_text(size = 9, color = "white"),
    axis.text.y = element_text(size = 8, color = "grey80"),
    axis.text.x = element_text(size = 8, color = "grey80"),
    plot.title = element_text(size = 12, face = "bold", hjust = 0.5, color = "white"),
    plot.subtitle = element_text(size = 10, hjust = 0.5, color = "grey80"),
    plot.caption = element_text(size = 8, hjust = 1, color = "grey60"),
    legend.position = "bottom",
    panel.grid.major = element_line(color = "grey30"),
    panel.grid.minor.x = element_blank(),
    legend.title = element_blank(),
    legend.text = element_text(size = 9, color = "white"),
    strip.text = element_text(size = 10, color = "white"),
    axis.ticks = element_blank(),
    plot.margin = margin(0.2, 0.8, 0.2, 0.8, "cm"),
    plot.background = element_rect(fill = "#1a1a1a", color = NA),
    panel.background = element_rect(fill = "#1a1a1a", color = NA),
    legend.background = element_rect(fill = "#1a1a1a", color = NA)
  )

# Aliases for backward compatibility
theme_survey <- theme_meo
theme_survey_dark <- theme_meo_dark

theme_set(theme_meo)

# ------------------------------------------------------------------------------
# Color Palettes
# ------------------------------------------------------------------------------

party_colors <- c(
  "Conservative" = "#1A4AAD",
  "Liberal" = "#D71B1E",
  "NDP" = "#F86634",
  "Green" = "#229A44",
  "Bloc Québécois" = "#00C4FF",
  "People's Party" = "#442D7B",
  "All Canadians" = "black"
)

platform_colors <- c(
  "Facebook" = "#3B5998",
  "YouTube" = "#FF0000",
  "Instagram" = "#C13584",
  "X" = "black",
  "X/Twitter" = "black",
  "Twitter" = "black",
  "TikTok" = "#69C9D0",
  "Tiktok" = "#69C9D0",
  "Bluesky" = "#1DA1F2",
  "Telegram" = "#0bc367"
)

meo_colors <- c("#467742", "#6D4A4D", "#434E7C", "#272B26", "#69A849",
                "#FF8200", "#6BADC6", "#F2E96B", "#D7D6D4")

entity_colors <- c(
  "Civil Society" = "#467742",
  "Influencer" = "#434E7C",
  "News" = "#6BADC6",
  "Politician" = "#FF8200"
)

country_colors <- c(
  "China" = "#DC143C",
  "India" = "#FF9933",
  "Russia" = "#0039A6",
  "US" = "#002868",
  "United States" = "#002868",
  "UK" = "#012169"
)

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------

#' Get MEO color by index (cycles if > 9)
meo_color <- function(i) {
  meo_colors[((i - 1) %% length(meo_colors)) + 1]
}

#' Scale for party colors
scale_fill_party <- function(...) scale_fill_manual(values = party_colors, ...)
scale_color_party <- function(...) scale_color_manual(values = party_colors, ...)

#' Scale for platform colors
scale_fill_platform <- function(...) scale_fill_manual(values = platform_colors, ...)
scale_color_platform <- function(...) scale_color_manual(values = platform_colors, ...)

#' Scale for entity colors
scale_fill_entity <- function(...) scale_fill_manual(values = entity_colors, ...)
scale_color_entity <- function(...) scale_color_manual(values = entity_colors, ...)

#' Scale for MEO colors
scale_fill_meo <- function(...) scale_fill_manual(values = meo_colors, ...)
scale_color_meo <- function(...) scale_color_manual(values = meo_colors, ...)

# ------------------------------------------------------------------------------
# Caption Functions
# ------------------------------------------------------------------------------

#' Generate survey caption with sample details
#'
#' @param n Sample size
#' @param start_date Start date of data collection
#' @param end_date End date of data collection
#' @param confidence Confidence level (default 0.95)
#' @param extra Additional caption text
#' @return Character string for plot caption
survey_caption <- function(n, start_date, end_date, confidence = 0.95, extra = NULL) {
  z <- qnorm(1 - (1 - confidence) / 2)
  moe <- z * sqrt(0.25 / n) * 100

  conf_text <- if (confidence == 0.95) {
    "19 times out of 20"
  } else if (confidence == 0.99) {
    "99 times out of 100"
  } else {
    paste0(confidence * 100, "% of the time")
  }

  caption <- sprintf(
    "Based on %s respondents surveyed %s to %s. A comparable random sample would be within \u00B1%.1f percentage points %s.",
    format(n, big.mark = ","),
    format(as.Date(start_date), "%B %d, %Y"),
    format(as.Date(end_date), "%B %d, %Y"),
    moe,
    conf_text
  )

  if (!is.null(extra)) caption <- paste(caption, extra)
  caption
}

#' Generate social/digital trace data caption
#'
#' @param n_posts Number of posts
#' @param n_accounts Number of unique accounts
#' @param start_date Start date of data
#' @param end_date End date of data
#' @param platforms Vector of platform names (optional)
#' @param extra Additional caption text
#' @return Character string for plot caption
social_caption <- function(n_posts, n_accounts, start_date, end_date, platforms = NULL, extra = NULL) {
  format_num <- function(x) {
    if (x >= 1e6) paste0(round(x / 1e6, 1), "M")
    else if (x >= 1e3) paste0(round(x / 1e3, 1), "K")
    else format(x, big.mark = ",")
  }

  platform_text <- if (!is.null(platforms) && length(platforms) > 0) {
    paste0(" across ", paste(platforms, collapse = ", "))
  } else ""

  caption <- sprintf(
    "Based on %s posts from %s accounts%s (%s to %s).",
    format_num(n_posts),
    format(n_accounts, big.mark = ","),
    platform_text,
    format(as.Date(start_date), "%B %d, %Y"),
    format(as.Date(end_date), "%B %d, %Y")
  )

  if (!is.null(extra)) caption <- paste(caption, extra)
  caption
}

# ------------------------------------------------------------------------------
# Save Functions
# ------------------------------------------------------------------------------

#' Save plot in multiple formats (bright and dark modes)
#'
#' @param plot ggplot object
#' @param name filename without extension
#' @param data optional data to save alongside
#' @param width plot width in inches
#' @param height plot height in inches
#' @param dpi resolution
save_plot <- function(plot, name, data = NULL, width = 6.5, height = 4.5, dpi = 300) {
  # If name contains a directory component or is absolute, use it directly
  # (supports skills and scripts that save outside analysis/figures/)
  if (grepl("/", name) || grepl("\\\\", name)) {
    # Strip .png extension if present so the pattern below works uniformly
    name_stem <- sub("\\.png$", "", name)
    fig_dir   <- dirname(name_stem)
    stem      <- basename(name_stem)

    dir.create(fig_dir, showWarnings = FALSE, recursive = TRUE)
    dark_dir <- file.path(fig_dir, "dark")
    trans_dir <- file.path(fig_dir, "transparent")
    dir.create(dark_dir, showWarnings = FALSE, recursive = TRUE)
    dir.create(trans_dir, showWarnings = FALSE, recursive = TRUE)

    ref_dir    <- file.path(fig_dir, "reference", stem)
    base_path  <- file.path(fig_dir, stem)
    dark_path  <- file.path(dark_dir, stem)
    trans_path <- file.path(trans_dir, stem)
  } else {
    dir.create("analysis/figures", showWarnings = FALSE, recursive = TRUE)
    dir.create("analysis/figures/dark", showWarnings = FALSE, recursive = TRUE)
    dir.create("analysis/figures/transparent", showWarnings = FALSE, recursive = TRUE)

    ref_dir    <- file.path("analysis/figures/reference", name)
    base_path  <- file.path("analysis/figures", name)
    dark_path  <- file.path("analysis/figures/dark", name)
    trans_path <- file.path("analysis/figures/transparent", name)
  }

  # Derive a clean stem for filenames in reference dir
  fig_stem <- basename(sub("\\.png$", "", name))

  dir.create(ref_dir, showWarnings = FALSE, recursive = TRUE)

  # Save bright version
  ggsave(paste0(base_path, ".png"), plot = plot,
         width = width, height = height, dpi = dpi, bg = "white")

  # Save dark version
  plot_dark <- plot + theme_meo_dark
  ggsave(paste0(dark_path, ".png"), plot = plot_dark,
         width = width, height = height, dpi = dpi, bg = "#1a1a1a")

  # Save transparent version (bright theme, no background)
  plot_trans <- plot + theme(
    plot.background = element_rect(fill = "transparent", color = NA),
    panel.background = element_rect(fill = "transparent", color = NA),
    legend.background = element_rect(fill = "transparent", color = NA),
    legend.box.background = element_rect(fill = "transparent", color = NA)
  )
  ggsave(paste0(trans_path, ".png"), plot = plot_trans,
         width = width, height = height, dpi = dpi, bg = "transparent")

  # Save reference materials in subdirectory
  ggsave(file.path(ref_dir, paste0(fig_stem, ".svg")), plot = plot,
         width = width, height = height, dpi = dpi, bg = "white")

  # Save underlying data as CSV for replication
  ggdat <- ggplot_build(plot)$data
  for (i in seq_along(ggdat)) {
    write.csv(ggdat[[i]], file.path(ref_dir, paste0("layer", i, "_data.csv")), row.names = FALSE)
  }

  # Save source data if provided
  if (!is.null(data)) {
    write.csv(data, file.path(ref_dir, "source_data.csv"), row.names = FALSE)
    saveRDS(data, file.path(ref_dir, "data.rds"))
  }

  # Save plot object for exact reproduction
  saveRDS(plot, file.path(ref_dir, "plot.rds"))

  message(paste("Saved:", fig_stem, "(bright + dark + transparent + reference data)"))
}

# ------------------------------------------------------------------------------
# Setup directories and locale
# ------------------------------------------------------------------------------

dir.create("analysis/figures", showWarnings = FALSE, recursive = TRUE)
dir.create("analysis/figures/dark", showWarnings = FALSE, recursive = TRUE)
dir.create("analysis/figures/transparent", showWarnings = FALSE, recursive = TRUE)
dir.create("analysis/figures/reference", showWarnings = FALSE, recursive = TRUE)
dir.create("analysis/tables", showWarnings = FALSE, recursive = TRUE)
dir.create("analysis/data", showWarnings = FALSE, recursive = TRUE)

Sys.setlocale("LC_TIME", "en_CA.UTF-8")

message("MEO theme loaded. Use theme_meo (bright) or theme_meo_dark.")
