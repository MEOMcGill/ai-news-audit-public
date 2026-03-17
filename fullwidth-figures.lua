-- Lua filter for MEO brief PDF:
-- 1. Page breaks before H1 sections (inside multicols)
-- 2. Full-width figures (break out of multicols)
-- 3. Section images (decorative, no caption)
-- 4. Bilingual divs (side-by-side EN/FR columns)

-- Track whether we're inside the template's initial multicols.
-- The first bilingual div should close it; subsequent ones re-open/close their own.
local first_bilingual = true

local function escape_latex(s)
  s = s:gsub("%%", "\\%%")
  s = s:gsub("&", "\\&")
  s = s:gsub("#", "\\#")
  s = s:gsub("%$", "\\$")
  s = s:gsub("_", "\\_")
  return s
end

function Header(el)
  -- Every H1 gets a page break (exec summary / key takeaways / why it matters
  -- are H2s inside bilingual divs, so they won't trigger this)
  if el.level == 1 then
    -- "Questions" continues after Context without a page break
    local title = pandoc.utils.stringify(el.content)
    if title == "Questions" then
      return nil
    end

    -- These sections start on a new page; others just get vertical space
    local newpage_sections = { Context = true, Methodology = true, Endnotes = true, Contributors = true }

    -- .single-column sections: break out of two-column for remaining content,
    -- then re-open multicols{2} so the template's \end{multicols} balances
    if el.classes:includes("single-column") then
      local sc_sep = newpage_sections[title] and "\\clearpage\n" or "\\vspace{16pt}\n"
      local break_latex =
        "\\end{multicols}\n" ..
        sc_sep ..
        "\\fontsize{9.5}{12.5}\\selectfont\n" ..
        "\\setlength{\\parskip}{8pt plus 2pt minus 1pt}\n"
      -- We'll handle the re-opening in a Div or at the end; for now
      -- this section is the last, so we open a dummy multicols for balance
      return {
        pandoc.RawBlock("latex", break_latex),
        el
      }
    end
    local sep = newpage_sections[title] and "\\clearpage\n" or "\\vspace{6pt}\n"
    local break_latex =
      "\\end{multicols}\n" ..
      sep ..
      "\\begin{multicols}{2}\n" ..
      "\\fontsize{9.5}{12.5}\\selectfont\n"
    return {
      pandoc.RawBlock("latex", break_latex),
      el
    }
  end
  return nil
end

function Figure(fig)
  local img = fig.content[1]
  if img == nil then return nil end

  local src = nil
  local caption_text = ""
  local img_classes = {}

  if img.t == "Plain" or img.t == "Para" then
    for _, inline in ipairs(img.content) do
      if inline.t == "Image" then
        src = inline.src
        caption_text = pandoc.utils.stringify(inline.caption)
        if inline.attr then
          img_classes = inline.attr.classes or {}
        end
      end
    end
  end

  if src == nil then return nil end

  -- Collect classes from figure and image
  local all_classes = {}
  if fig.attr then
    for _, c in ipairs(fig.attr.classes or {}) do table.insert(all_classes, c) end
  end
  for _, c in ipairs(img_classes) do table.insert(all_classes, c) end

  local is_section_image = false
  for _, cls in ipairs(all_classes) do
    if cls == "section-image" then is_section_image = true end
  end

  if is_section_image then
    -- Decorative section images: slim banner (1.2in tall, cropped), no caption
    local latex = string.format(
      "\\end{multicols}\n" ..
      "\\vspace{2pt}\n" ..
      "\\IfFileExists{%s}{%%\n" ..
      "\\noindent\\begin{tikzpicture}\n" ..
      "  \\clip (0,0) rectangle (\\textwidth, 1.2in);\n" ..
      "  \\node[anchor=south west, inner sep=0pt] at (0,0) {\\includegraphics[width=\\textwidth]{%s}};\n" ..
      "\\end{tikzpicture}%%\n" ..
      "}{}\n" ..
      "\\vspace{2pt}\n" ..
      "\\begin{multicols}{2}\n" ..
      "\\fontsize{9.5}{12.5}\\selectfont\n",
      src, src
    )
    return pandoc.RawBlock("latex", latex)
  end

  -- Check for newpage, bottom, and inplace classes
  local needs_newpage = false
  local place_bottom = false
  local place_inplace = false
  for _, cls in ipairs(all_classes) do
    if cls == "newpage" then needs_newpage = true end
    if cls == "bottom" then place_bottom = true end
    if cls == "inplace" then place_inplace = true end
  end

  local safe_caption = escape_latex(caption_text)

  -- Inplace figures: no float, just image + caption right where they appear
  if place_inplace then
    local pre = needs_newpage
      and "\\end{multicols}\n\\clearpage\n"
      or  "\\end{multicols}\n\\vspace{4pt}\n"
    local latex = string.format(
      pre ..
      "\\noindent\\includegraphics[width=\\textwidth, trim=0 0 0 0, clip]{%s}\n" ..
      "\\par\\vspace{-6pt}\n" ..
      "{\\fontsize{8.5}{11}\\selectfont\\textbf{%s}\\par}\n" ..
      "\\vspace{4pt}\n" ..
      "\\begin{multicols}{2}\n" ..
      "\\fontsize{9.5}{12.5}\\selectfont\n",
      src, safe_caption
    )
    return pandoc.RawBlock("latex", latex)
  end

  -- Figure placement: [!b] for bottom, [H] for exact position
  local float_pos = place_bottom and "!b" or "H"

  -- Regular figures: full-width with bold caption
  local pre_figure = needs_newpage
    and "\\end{multicols}\n\\clearpage\n"
    or  "\\end{multicols}\n\\vspace{4pt}\n"
  local latex = string.format(
    pre_figure ..
    "\\begin{figure}[" .. float_pos .. "]\n" ..
    "\\noindent\\includegraphics[width=\\textwidth]{%s}\n" ..
    "\\par\\vspace{8pt}\n" ..
    "{\\fontsize{8.5}{11}\\selectfont\\textbf{%s}\\par}\n" ..
    "\\end{figure}\n" ..
    "\\vspace{2pt}\n" ..
    "\\begin{multicols}{2}\n" ..
    "\\fontsize{9.5}{12.5}\\selectfont\n",
    src, safe_caption
  )
  return pandoc.RawBlock("latex", latex)
end

function Div(el)
  -- AI disclosure box: italic text in a light grey box, full-width
  if el.classes:includes("ai-disclosure") then
    local result = pandoc.Blocks{}
    result:insert(pandoc.RawBlock("latex",
      "\\end{multicols}\n" ..
      "\\vspace{6pt}\n" ..
      "\\noindent\\colorbox{gray!8}{\\parbox{\\dimexpr\\textwidth-2\\fboxsep}{%\n" ..
      "\\fontsize{8.5}{11.5}\\selectfont\\itshape\\parskip=4pt\n"
    ))
    result:extend(el.content)
    result:insert(pandoc.RawBlock("latex",
      "}}\n" ..
      "\\vspace{6pt}\n" ..
      "\\begin{multicols}{2}\n" ..
      "\\fontsize{9.5}{12.5}\\selectfont\n"
    ))
    return result
  end

  -- AI disclosure inline: italic text in a light grey box, within a column (no multicols break)
  if el.classes:includes("ai-disclosure-inline") then
    local result = pandoc.Blocks{}
    result:insert(pandoc.RawBlock("latex",
      "\\vfill\\vspace{20pt}\n" ..
      "\\noindent\\colorbox{gray!8}{\\parbox{\\dimexpr\\linewidth-2\\fboxsep}{%\n" ..
      "\\fontsize{7.5}{10}\\selectfont\\itshape\\parskip=4pt\n"
    ))
    result:extend(el.content)
    result:insert(pandoc.RawBlock("latex",
      "}}\n" ..
      "\\vspace{4pt}\n"
    ))
    return result
  end

  -- Bilingual divs: break out of multicols, render as two side-by-side minipage columns
  if el.classes:includes("bilingual") then
    local children = el.content
    -- Collect the two child divs (EN left, FR right)
    local left_blocks = pandoc.Blocks{}
    local right_blocks = pandoc.Blocks{}
    local which = "left"
    for _, block in ipairs(children) do
      if block.t == "Div" then
        if which == "left" then
          left_blocks:extend(block.content)
          which = "right"
        else
          right_blocks:extend(block.content)
        end
      end
    end

    -- Insert \parskip=6pt after every Header block so titlesec can't zero it
    local function inject_parskip(blocks)
      local out = pandoc.Blocks{}
      for _, b in ipairs(blocks) do
        out:insert(b)
        if b.t == "Header" then
          out:insert(pandoc.RawBlock("latex", "\\parskip=8pt"))
        end
      end
      return out
    end

    local result = pandoc.Blocks{}
    local pre = first_bilingual
      and "\\setcounter{page}{1}\n" ..
          "\\fontsize{9.5}{13}\\selectfont\n" ..
          "\\setlength{\\parskip}{8pt plus 2pt minus 1pt}\n" ..
          "\\vspace*{-\\topskip}\\vspace*{-\\baselineskip}\\vspace*{-\\parskip}\n" ..
          "\\noindent\\begin{minipage}[t]{0.44\\textwidth}\n" ..
          "\\parskip=8pt\n" ..
          "\\fontsize{9.5}{12.5}\\selectfont\n"
      or  "\\end{multicols}\n" ..
          "\\vspace{10pt}\n" ..
          "\\noindent\\begin{minipage}[t]{0.45\\textwidth}\n" ..
          "\\parskip=8pt\n" ..
          "\\fontsize{9.5}{12.5}\\selectfont\n"
    first_bilingual = false
    result:insert(pandoc.RawBlock("latex", pre))
    result:extend(inject_parskip(left_blocks))
    result:insert(pandoc.RawBlock("latex",
      "\\end{minipage}\\hfill\n" ..
      "\\begin{minipage}[t]{0.52\\textwidth}\n" ..
      "\\parskip=8pt\n" ..
      "\\fontsize{9.5}{12.5}\\selectfont\n"
    ))
    result:extend(inject_parskip(right_blocks))
    result:insert(pandoc.RawBlock("latex",
      "\\end{minipage}\n" ..
      "\\vspace{10pt}\n" ..
      "\\begin{multicols}{2}\n" ..
      "\\fontsize{9.5}{12.5}\\selectfont\n"
    ))
    return result
  end
  return nil
end
