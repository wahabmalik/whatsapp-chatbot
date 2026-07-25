(function (window) {
  "use strict";

  var ALLOWED_CATEGORIES = ["MARKETING", "UTILITY", "AUTHENTICATION"];

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatEstimateSummary(estimate) {
    if (!estimate) {
      return "Projected spend unavailable.";
    }
    var inputs = estimate.inputs || {};
    var spend = estimate.projected_spend_inr != null
      ? "INR " + estimate.projected_spend_inr
      : "unavailable";
    var threshold = estimate.threshold_inr != null
      ? "INR " + estimate.threshold_inr
      : "n/a";
    return (
      "India-only projected spend: <strong>" + escapeHtml(spend) + "</strong>" +
      " · Category: <strong>" + escapeHtml(inputs.template_category || "n/a") + "</strong>" +
      " · Recipients: <strong>" + escapeHtml(inputs.recipient_count != null ? inputs.recipient_count : "n/a") + "</strong>" +
      " · Warning threshold: <strong>" + escapeHtml(threshold) + "</strong>"
    );
  }

  function postForm(url, csrfToken, fields) {
    var body = new URLSearchParams();
    Object.keys(fields || {}).forEach(function (key) {
      if (fields[key] != null) {
        body.set(key, String(fields[key]));
      }
    });
    body.set("csrf_token", csrfToken);
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken,
        "Content-Type": "application/x-www-form-urlencoded"
      },
      body: body.toString()
    }).then(function (res) {
      return res.json().then(function (payload) {
        return { status: res.status, payload: payload || {} };
      });
    });
  }

  function bindDraftControls(root, options) {
    var csrfToken = options.csrfToken;
    var onDraftsChanged = options.onDraftsChanged || function () {};
    var statusEl = options.statusEl || null;

    function setStatus(message) {
      if (statusEl) {
        statusEl.textContent = message;
      }
    }

    function setEstimateMessage(card, html, isError) {
      var estimateEl = card.querySelector("[data-starter-estimate]");
      if (!estimateEl) {
        return;
      }
      estimateEl.innerHTML = html;
      estimateEl.classList.toggle("is-error", !!isError);
    }

    function setConfirmVisibility(card, visible, estimate) {
      var confirmBox = card.querySelector("[data-starter-confirm-box]");
      if (!confirmBox) {
        return;
      }
      confirmBox.hidden = !visible;
      if (visible && estimate) {
        var summary = confirmBox.querySelector("[data-starter-confirm-summary]");
        if (summary) {
          summary.innerHTML = formatEstimateSummary(estimate);
        }
      }
    }

    function currentRecipientCount(card) {
      var input = card.querySelector("[data-starter-recipient-count]");
      return input ? String(input.value || "").trim() : "";
    }

    function previewEstimate(card) {
      var slug = card.getAttribute("data-workflow-slug");
      if (!slug) {
        return Promise.resolve();
      }
      var recipientCount = currentRecipientCount(card);
      setEstimateMessage(card, "Calculating India-only projected spend...", false);
      setConfirmVisibility(card, false, null);
      return postForm(
        "/onboarding/starter-pack/draft/" + encodeURIComponent(slug) + "/activate",
        csrfToken,
        {
          recipient_count: recipientCount,
          preview_only: "true"
        }
      ).then(function (result) {
        var payload = result.payload;
        if (payload.blocked_reason === "estimation_failed") {
          setEstimateMessage(
            card,
            escapeHtml(payload.message || (payload.estimate && payload.estimate.estimation_error) || "Could not estimate projected spend."),
            true
          );
          return;
        }
        if (!payload.ok && !payload.estimate) {
          setEstimateMessage(card, escapeHtml(payload.message || "Could not estimate projected spend."), true);
          return;
        }
        setEstimateMessage(card, formatEstimateSummary(payload.estimate), false);
        if (payload.estimate && payload.estimate.threshold_exceeded) {
          setConfirmVisibility(card, true, payload.estimate);
        }
      }).catch(function () {
        setEstimateMessage(card, "Could not estimate projected spend.", true);
      });
    }

    function activateDraft(card, explicitConfirm) {
      var slug = card.getAttribute("data-workflow-slug");
      if (!slug) {
        return Promise.resolve();
      }
      var fields = {
        recipient_count: currentRecipientCount(card)
      };
      if (explicitConfirm) {
        fields.explicit_cost_confirmation = "true";
      }
      setStatus("Activating starter draft...");
      return postForm(
        "/onboarding/starter-pack/draft/" + encodeURIComponent(slug) + "/activate",
        csrfToken,
        fields
      ).then(function (result) {
        var payload = result.payload;
        if (payload.blocked_reason === "estimation_failed") {
          setEstimateMessage(
            card,
            escapeHtml(payload.message || "Could not estimate projected spend. Fix the pricing inputs and retry."),
            true
          );
          setStatus(payload.message || "Activation blocked: estimation failed.");
          return;
        }
        if (payload.blocked_reason === "cost_confirmation_required") {
          setEstimateMessage(card, formatEstimateSummary(payload.estimate), false);
          setConfirmVisibility(card, true, payload.estimate);
          setStatus("Projected spend meets or exceeds the warning threshold. Confirm to continue.");
          return;
        }
        if (!payload.ok) {
          setStatus(payload.message || "Draft activation blocked.");
          if (payload.estimate) {
            setEstimateMessage(card, formatEstimateSummary(payload.estimate), false);
          }
          return;
        }
        setConfirmVisibility(card, false, null);
        if (payload.estimate) {
          setEstimateMessage(card, formatEstimateSummary(payload.estimate), false);
        }
        setStatus("Starter draft activated.");
        onDraftsChanged();
      }).catch(function () {
        setStatus("Draft activation failed.");
      });
    }

    function updateCategory(card) {
      var slug = card.getAttribute("data-workflow-slug");
      var select = card.querySelector("[data-starter-category]");
      if (!slug || !select) {
        return Promise.resolve();
      }
      var title = card.getAttribute("data-draft-title") || slug;
      var body = card.getAttribute("data-draft-body") || "";
      return postForm(
        "/onboarding/starter-pack/draft/" + encodeURIComponent(slug) + "/update",
        csrfToken,
        {
          title: title,
          body: body,
          category_label: select.value
        }
      ).then(function (result) {
        if (!result.payload.ok) {
          setStatus(result.payload.message || "Could not update template category.");
          return;
        }
        card.setAttribute("data-draft-title", result.payload.draft.title || title);
        card.setAttribute("data-draft-body", result.payload.draft.body || body);
        setStatus("Category updated. Recalculating estimate...");
        return previewEstimate(card);
      }).catch(function () {
        setStatus("Could not update template category.");
      });
    }

    root.querySelectorAll("[data-starter-draft-card]").forEach(function (card) {
      var recipientInput = card.querySelector("[data-starter-recipient-count]");
      var previewBtn = card.querySelector("[data-starter-preview]");
      var activateBtn = card.querySelector("[data-starter-activate]");
      var confirmBtn = card.querySelector("[data-starter-confirm-activate]");
      var categorySelect = card.querySelector("[data-starter-category]");
      var previewTimer = null;

      if (recipientInput) {
        recipientInput.addEventListener("input", function () {
          setConfirmVisibility(card, false, null);
          if (previewTimer) {
            window.clearTimeout(previewTimer);
          }
          previewTimer = window.setTimeout(function () {
            previewEstimate(card);
          }, 250);
        });
      }
      if (previewBtn) {
        previewBtn.addEventListener("click", function () {
          previewEstimate(card);
        });
      }
      if (activateBtn) {
        activateBtn.addEventListener("click", function () {
          activateDraft(card, false);
        });
      }
      if (confirmBtn) {
        confirmBtn.addEventListener("click", function () {
          activateDraft(card, true);
        });
      }
      if (categorySelect) {
        categorySelect.addEventListener("change", function () {
          updateCategory(card);
        });
      }
    });
  }

  function renderDraftCardHtml(draft, options) {
    options = options || {};
    var slug = escapeHtml(draft.workflow_slug || "");
    var title = escapeHtml(draft.title || draft.workflow_slug || "");
    var body = escapeHtml(draft.body || "");
    var category = String(draft.category_label || "UTILITY").toUpperCase();
    var categoryOptions = ALLOWED_CATEGORIES.map(function (label) {
      return '<option value="' + label + '"' + (label === category ? " selected" : "") + ">" + label + "</option>";
    }).join("");
    var compact = !!options.compact;

    return (
      '<li class="starter-draft-card" data-starter-draft-card' +
        ' data-workflow-slug="' + slug + '"' +
        ' data-draft-title="' + title + '"' +
        ' data-draft-body="' + body + '">' +
        (compact
          ? '<span>' + slug + '</span><span>' + escapeHtml(category) + '</span><span>' + escapeHtml(String(draft.draft_status || "").toUpperCase()) + '</span>'
          : '<strong>' + title + '</strong>' +
            '<div class="starter-draft-meta">' +
              'Workflow: <code>' + slug + '</code> · Status: ' + escapeHtml(draft.draft_status || "") +
            '</div>' +
            '<p class="starter-draft-body">' + body + '</p>') +
        '<div class="starter-cost-guard">' +
          '<p class="starter-cost-note">India-only projected spend estimate (not an invoice).</p>' +
          '<div class="starter-cost-controls">' +
            '<label class="starter-cost-field">' +
              '<span>Category</span>' +
              '<select data-starter-category>' + categoryOptions + '</select>' +
            '</label>' +
            '<label class="starter-cost-field">' +
              '<span>Recipients</span>' +
              '<input type="number" min="1" step="1" inputmode="numeric" data-starter-recipient-count placeholder="e.g. 25" />' +
            '</label>' +
            '<button type="button" class="button-link button-secondary" data-starter-preview>Preview estimate</button>' +
            '<button type="button" class="button-link" data-starter-activate>Activate</button>' +
          '</div>' +
          '<div class="starter-estimate" data-starter-estimate>Enter a recipient count to preview India-only projected spend.</div>' +
          '<div class="starter-confirm-box" data-starter-confirm-box hidden>' +
            '<p data-starter-confirm-summary></p>' +
            '<p class="starter-confirm-copy">Projected spend meets or exceeds the warning threshold. Confirm to activate.</p>' +
            '<button type="button" class="button-link" data-starter-confirm-activate>Confirm estimate and activate</button>' +
          '</div>' +
        '</div>' +
      '</li>'
    );
  }

  window.StarterPackCostGuardrails = {
    ALLOWED_CATEGORIES: ALLOWED_CATEGORIES,
    renderDraftCardHtml: renderDraftCardHtml,
    bindDraftControls: bindDraftControls,
    formatEstimateSummary: formatEstimateSummary
  };
})(window);
