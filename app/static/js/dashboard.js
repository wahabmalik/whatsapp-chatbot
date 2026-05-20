(function () {
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function showToast(message, isError) {
    var region = document.getElementById("toast-region");
    if (!region) {
      return;
    }
    var node = document.createElement("div");
    node.className = "toast" + (isError ? " error" : "");
    node.setAttribute("role", isError ? "alert" : "status");
    node.textContent = message;
    region.appendChild(node);
    window.setTimeout(function () {
      if (node.parentNode) {
        node.parentNode.removeChild(node);
      }
    }, 3000);
  }

  function withBusy(button, callback) {
    if (!button) {
      return callback();
    }
    if (button.disabled) {
      return Promise.resolve();
    }
    var originalLabel = button.textContent;
    var loadingLabel = button.getAttribute("data-loading-label") || "Working...";
    button.disabled = true;
    button.classList.add("is-loading");
    button.textContent = loadingLabel;
    return Promise.resolve()
      .then(callback)
      .finally(function () {
        button.disabled = false;
        button.classList.remove("is-loading");
        button.textContent = originalLabel;
      });
  }

  var copyButtons = document.querySelectorAll("[data-copy-target]");
  copyButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var id = button.getAttribute("data-copy-target");
      var input = document.getElementById(id);
      if (!input) {
        return;
      }
      input.select();
      try {
        document.execCommand("copy");
        showToast("Copied", false);
      } catch (err) {
        showToast("Copy failed", true);
      }
    });
  });

  var form = document.getElementById("agent-form");
  if (form) {
    var saveButton = document.getElementById("save-agent");
    var initial = form.querySelector("input[name='agent_code']:checked");
    var initialValue = initial ? initial.value : "";

    if (saveButton && initialValue) {
      saveButton.disabled = true;
    }

    form.addEventListener("change", function () {
      var selected = form.querySelector("input[name='agent_code']:checked");
      if (saveButton && selected) {
        saveButton.disabled = selected.value === initialValue;
      }
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var data = new FormData(form);
      fetch(form.action, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: data,
      })
        .then(function (response) {
          return response.json().then(function (payload) {
            return { ok: response.ok, payload: payload };
          });
        })
        .then(function (result) {
          showToast(result.payload.message || "Saved", !result.ok);
          if (result.ok) {
            initialValue = data.get("agent_code") || initialValue;
            if (saveButton) {
              saveButton.disabled = true;
            }
            window.setTimeout(function () {
              window.location.reload();
            }, 300);
          }
        })
        .catch(function () {
          showToast("Could not save agent selection", true);
        });
    });
  }

  var revealButtons = document.querySelectorAll("[data-reveal-number]");
  revealButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var cell = button.closest("tr");
      if (!cell) {
        return;
      }
      var masked = cell.querySelector("[data-masked]");
      var full = cell.querySelector("[data-full]");
      if (!masked || !full) {
        return;
      }
      masked.classList.toggle("hide");
      full.classList.toggle("hide");
      var expanded = !full.classList.contains("hide");
      button.textContent = expanded ? "Hide" : "Reveal";
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
  });

  var detailButtons = document.querySelectorAll("[data-toggle-detail]");
  detailButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var row = button.closest("tr");
      if (!row) {
        return;
      }
      var detailRow = row.nextElementSibling;
      if (!detailRow || !detailRow.hasAttribute("data-detail-row")) {
        return;
      }

      var hidden = detailRow.classList.contains("hide");
      if (hidden) {
        detailRow.classList.remove("hide");
      } else {
        detailRow.classList.add("hide");
      }

      var expanded = !detailRow.classList.contains("hide");
      button.textContent = expanded ? "Collapse" : "Expand";
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
  });

  var threadInspectorForm = document.querySelector("[data-thread-inspector-form]");
  if (threadInspectorForm) {
    threadInspectorForm.addEventListener("submit", function (event) {
      event.preventDefault();

      var endpoint = threadInspectorForm.getAttribute("data-endpoint");
      var input = threadInspectorForm.querySelector("input[name='user_id']");
      var errorNode = document.querySelector("[data-thread-inspector-error]");
      var resultsNode = document.querySelector("[data-thread-inspector-results]");
      var userNode = document.querySelector("[data-thread-inspector-user]");
      var contextList = document.querySelector("[data-thread-context-list]");
      var activityBody = document.querySelector("[data-thread-activity-body]");

      if (!endpoint || !input) {
        return;
      }

      if (errorNode) {
        errorNode.classList.add("hide");
        errorNode.textContent = "";
      }
      if (resultsNode) {
        resultsNode.classList.add("hide");
      }

      var userId = (input.value || "").trim();
      if (!userId) {
        if (errorNode) {
          errorNode.textContent = "Enter a thread user id.";
          errorNode.classList.remove("hide");
        }
        return;
      }

      fetch(endpoint + "?user_id=" + encodeURIComponent(userId))
        .then(function (response) {
          return response.json().then(function (payload) {
            return { ok: response.ok, payload: payload };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.payload || !result.payload.ok) {
            var message = (result.payload && result.payload.message) || "Could not load thread details";
            if (errorNode) {
              errorNode.textContent = message;
              errorNode.classList.remove("hide");
            }
            return;
          }

          var thread = result.payload.thread || {};
          var context = thread.conversation_context || [];
          var activity = thread.recent_activity || [];

          if (userNode) {
            userNode.textContent = thread.user_id_masked || "Unknown";
          }

          if (contextList) {
            contextList.innerHTML = "";
            if (!context.length) {
              var emptyContext = document.createElement("li");
              emptyContext.textContent = "No context yet for this thread.";
              contextList.appendChild(emptyContext);
            } else {
              context.forEach(function (row) {
                var item = document.createElement("li");
                var timestamp = document.createElement("span");
                timestamp.textContent = row.timestamp || "-";
                var role = document.createElement("span");
                role.textContent = (row.role || "-").toUpperCase();
                var text = document.createElement("span");
                text.textContent = row.text || "-";
                item.appendChild(timestamp);
                item.appendChild(role);
                item.appendChild(text);
                contextList.appendChild(item);
              });
            }
          }

          if (activityBody) {
            activityBody.innerHTML = "";
            if (!activity.length) {
              var emptyRow = document.createElement("tr");
              var emptyCell = document.createElement("td");
              emptyCell.colSpan = 4;
              emptyCell.textContent = "No activity entries found for this thread.";
              emptyRow.appendChild(emptyCell);
              activityBody.appendChild(emptyRow);
            } else {
              activity.forEach(function (row) {
                var tr = document.createElement("tr");

                var timeCell = document.createElement("td");
                timeCell.textContent = row.timestamp || "-";
                tr.appendChild(timeCell);

                var fromCell = document.createElement("td");
                fromCell.textContent = row.from_masked || "-";
                tr.appendChild(fromCell);

                var statusCell = document.createElement("td");
                statusCell.textContent = row.status || "-";
                tr.appendChild(statusCell);

                var previewCell = document.createElement("td");
                previewCell.textContent = row.preview || "-";
                tr.appendChild(previewCell);

                activityBody.appendChild(tr);
              });
            }
          }

          if (resultsNode) {
            resultsNode.classList.remove("hide");
          }
        })
        .catch(function () {
          if (errorNode) {
            errorNode.textContent = "Could not load thread details";
            errorNode.classList.remove("hide");
          }
        });
    });
  }

  var setupVerifyButton = document.querySelector("[data-setup-verify]");
  if (setupVerifyButton) {
    setupVerifyButton.addEventListener("click", function () {
      var endpoint = setupVerifyButton.getAttribute("data-verify-url");
      if (!endpoint || setupVerifyButton.disabled) {
        return;
      }

      var okMessage = document.querySelector("[data-setup-verify-success]");
      var errorMessage = document.querySelector("[data-setup-verify-error]");
      if (okMessage) {
        okMessage.classList.add("hide");
      }
      if (errorMessage) {
        errorMessage.classList.add("hide");
      }

      withBusy(setupVerifyButton, function () {
        return fetch(endpoint, { method: "POST", headers: { "X-CSRFToken": getCsrfToken() } })
          .then(function (response) {
            return response.json().then(function (payload) {
              return { ok: response.ok, payload: payload };
            });
          })
          .then(function (result) {
            var message = result.payload.message || (result.ok ? "Verification succeeded" : "Verification failed");
            if (result.ok) {
              if (okMessage) {
                okMessage.textContent = message;
                okMessage.classList.remove("hide");
              }
              showToast(message, false);
            } else {
              if (errorMessage) {
                errorMessage.textContent = message;
                errorMessage.classList.remove("hide");
              }
              showToast(message, true);
            }
          })
          .catch(function () {
            var fallback = "Could not run verification check";
            if (errorMessage) {
              errorMessage.textContent = fallback;
              errorMessage.classList.remove("hide");
            }
            showToast(fallback, true);
          });
      });
    });
  }

  var setupStatusNode = document.querySelector("[data-setup-status-url]");
  if (setupStatusNode) {
    var setupStatusEndpoint = setupStatusNode.getAttribute("data-setup-status-url");
    var setupSummaryNode = document.querySelector("[data-setup-status-summary]");
    var setupStepsNode = document.querySelector("[data-setup-next-steps]");

    if (setupStatusEndpoint && setupSummaryNode && setupStepsNode) {
      fetch(setupStatusEndpoint)
        .then(function (response) {
          return response.json().then(function (payload) {
            return { ok: response.ok, payload: payload };
          });
        })
        .then(function (result) {
          setupStepsNode.innerHTML = "";

          if (!result.ok || !result.payload) {
            setupSummaryNode.textContent = "Could not load setup status guidance.";
            return;
          }

          var summary = result.payload.summary || {};
          var configured = Number(summary.configured || 0);
          var total = Number(summary.total_required || 0);
          var missing = Number(summary.missing || 0);
          setupSummaryNode.textContent = "Configured " + configured + " of " + total + " required keys.";
          if (missing > 0) {
            setupSummaryNode.textContent += " " + missing + " still missing.";
          }

          var steps = result.payload.next_steps || [];
          if (!steps.length) {
            var emptyItem = document.createElement("li");
            emptyItem.textContent = "No additional actions required.";
            setupStepsNode.appendChild(emptyItem);
            return;
          }

          steps.forEach(function (step) {
            var item = document.createElement("li");
            item.textContent = step;
            setupStepsNode.appendChild(item);
          });
        })
        .catch(function () {
          setupSummaryNode.textContent = "Could not load setup status guidance.";
        });
    }
  }

    var openAiKeyForm = document.querySelector("[data-openai-key-form]");
    if (openAiKeyForm) {
      openAiKeyForm.addEventListener("submit", function (event) {
        event.preventDefault();

        var endpoint = openAiKeyForm.getAttribute("data-save-url");
        if (!endpoint) {
          showToast("Missing save endpoint", true);
          return;
        }

        var okMessage = document.querySelector("[data-openai-save-success]");
        var errorMessage = document.querySelector("[data-openai-save-error]");
        if (okMessage) {
          okMessage.classList.add("hide");
        }
        if (errorMessage) {
          errorMessage.classList.add("hide");
        }

        var saveButton = openAiKeyForm.querySelector("button[type='submit']");
        withBusy(saveButton, function () {
          return fetch(endpoint, {
            method: "POST",
            headers: { "X-CSRFToken": getCsrfToken() },
            body: new FormData(openAiKeyForm),
          })
            .then(function (response) {
              return response.json().then(function (payload) {
                return { ok: response.ok, payload: payload };
              });
            })
            .then(function (result) {
              var message = result.payload.message || (result.ok ? "Saved" : "Save failed");
              if (result.ok) {
                if (okMessage) {
                  okMessage.textContent = message;
                  okMessage.classList.remove("hide");
                }
                showToast(message, false);
                window.setTimeout(function () {
                  window.location.reload();
                }, 300);
              } else {
                if (errorMessage) {
                  errorMessage.textContent = message;
                  errorMessage.classList.remove("hide");
                }
                showToast(message, true);
              }
            })
            .catch(function () {
              var fallback = "Could not save OpenAI API key";
              if (errorMessage) {
                errorMessage.textContent = fallback;
                errorMessage.classList.remove("hide");
              }
              showToast(fallback, true);
            });
        });
      });
    }

  function renderCounterTable(counters) {
    var target = document.querySelector("[data-counters-table]");
    if (!target) {
      return;
    }

    target.innerHTML = "";
    var keys = Object.keys(counters || {}).sort();
    if (!keys.length) {
      var row = document.createElement("tr");
      row.innerHTML = "<td colspan='2'>No data yet</td>";
      target.appendChild(row);
      return;
    }

    keys.forEach(function (key) {
      var row = document.createElement("tr");
      row.innerHTML = "<td></td><td></td>";
      row.children[0].textContent = key;
      row.children[1].textContent = counters[key];
      target.appendChild(row);
    });
  }

  function refreshMetrics() {
    fetch("/api/metrics")
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        renderCounterTable(payload.counters || {});
        document.querySelectorAll("[data-metric-counter]").forEach(function (node) {
          var key = node.getAttribute("data-metric-counter");
          node.textContent = (payload.counters || {})[key] || 0;
        });
        document.querySelectorAll("[data-metric-duration]").forEach(function (node) {
          var key = node.getAttribute("data-metric-duration");
          var value = (((payload.durations || {}).averages || {})[key]);
          node.textContent = typeof value === "number" ? value.toFixed(2) + "s" : "No data yet";
        });
        var refreshed = document.querySelector("[data-refreshed-at]");
        if (refreshed) {
          refreshed.textContent = new Date().toISOString().slice(11, 19) + " UTC";
        }
      })
      .catch(function () {
        showToast("Metrics refresh failed", true);
      });
  }

  function renderAnalyticsBarRows(container, rows, valueSelector, valueFormatter) {
    if (!container) {
      return;
    }

    container.innerHTML = "";
    if (!rows || !rows.length) {
      var empty = document.createElement("p");
      empty.className = "subtle-help";
      empty.textContent = "No data yet.";
      container.appendChild(empty);
      return;
    }

    var maxValue = 0;
    rows.forEach(function (row) {
      maxValue = Math.max(maxValue, Number(valueSelector(row) || 0));
    });
    if (maxValue <= 0) {
      maxValue = 1;
    }

    rows.forEach(function (row) {
      var value = Number(valueSelector(row) || 0);
      var percent = Math.max(0, Math.min(100, (value / maxValue) * 100));
      var barRow = document.createElement("div");
      barRow.className = "bar-row";

      var label = document.createElement("span");
      label.textContent = String(row.date || "-").slice(5);
      barRow.appendChild(label);

      var track = document.createElement("span");
      track.className = "bar-track";
      var fill = document.createElement("i");
      fill.style.width = percent.toFixed(2) + "%";
      track.appendChild(fill);
      barRow.appendChild(track);

      var valueNode = document.createElement("span");
      valueNode.textContent = valueFormatter(value, row);
      barRow.appendChild(valueNode);

      container.appendChild(barRow);
    });
  }

  function renderDeliveryBreakdown(container, breakdown) {
    if (!container) {
      return;
    }

    var success = Number((breakdown || {}).success || 0);
    var retry = Number((breakdown || {}).retry || 0);
    var failure = Number((breakdown || {}).failure || 0);
    var total = success + retry + failure;

    container.innerHTML = "";
    [
      { label: "Success", value: success },
      { label: "Retry", value: retry },
      { label: "Failure", value: failure },
    ].forEach(function (row) {
      var percent = total > 0 ? (row.value / total) * 100 : 0;
      var barRow = document.createElement("div");
      barRow.className = "bar-row";

      var label = document.createElement("span");
      label.textContent = row.label;
      barRow.appendChild(label);

      var track = document.createElement("span");
      track.className = "bar-track";
      var fill = document.createElement("i");
      fill.style.width = percent.toFixed(2) + "%";
      track.appendChild(fill);
      barRow.appendChild(track);

      var valueNode = document.createElement("span");
      valueNode.textContent = row.value + " (" + percent.toFixed(1) + "%)";
      barRow.appendChild(valueNode);

      container.appendChild(barRow);
    });
  }

  function refreshAnalyticsSummary() {
    var analyticsNode = document.querySelector("[data-analytics-section]");
    if (!analyticsNode) {
      return;
    }

    var endpoint = analyticsNode.getAttribute("data-analytics-summary-url") || "/api/analytics/summary";
    var statusNode = document.querySelector("[data-analytics-status]");
    var insufficientNode = document.querySelector("[data-analytics-insufficient]");
    var escalationRateNode = document.querySelector("[data-analytics-escalation-rate]");
    var deliveryTotalNode = document.querySelector("[data-analytics-delivery-total]");
    var latencyP95Node = document.querySelector("[data-analytics-latency-p95]");
    var coverageHoursNode = document.querySelector("[data-analytics-coverage-hours]");
    var volumeNode = document.querySelector("[data-analytics-volume-trend]");
    var deliveryNode = document.querySelector("[data-analytics-delivery-breakdown]");
    var latencyTrendNode = document.querySelector("[data-analytics-latency-trend]");

    fetch(endpoint)
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.payload || !result.payload.ok) {
          throw new Error("analytics_fetch_failed");
        }

        var payload = result.payload;
        var volumeTrend = payload.volume_trend || [];
        var escalationTrend = payload.escalation_trend || [];
        var deliveryBreakdown = payload.delivery_breakdown || {};
        var latencySummary = payload.latency_summary || {};
        var latencyTrend = payload.latency_trend || [];
        var coverageHours = Number(payload.coverage_hours || 0);
        var insufficientData = Boolean(payload.insufficient_data);

        var totalVolume = 0;
        volumeTrend.forEach(function (item) {
          totalVolume += Number(item.count || 0);
        });
        var totalEscalations = 0;
        escalationTrend.forEach(function (item) {
          totalEscalations += Number(item.count || 0);
        });
        var escalationRate = totalVolume > 0 ? (totalEscalations / totalVolume) * 100 : 0;

        var deliveryTotal = Number(deliveryBreakdown.success || 0)
          + Number(deliveryBreakdown.retry || 0)
          + Number(deliveryBreakdown.failure || 0);

        if (statusNode) {
          statusNode.textContent = "Updated " + new Date().toISOString().slice(11, 19) + " UTC";
        }
        if (insufficientNode) {
          if (insufficientData) {
            insufficientNode.classList.remove("hide");
          } else {
            insufficientNode.classList.add("hide");
          }
        }
        if (escalationRateNode) {
          escalationRateNode.textContent = escalationRate.toFixed(1) + "%";
        }
        if (deliveryTotalNode) {
          deliveryTotalNode.textContent = String(deliveryTotal);
        }
        if (latencyP95Node) {
          latencyP95Node.textContent = String(Number(latencySummary.p95_ms || 0).toFixed(0)) + "ms";
        }
        if (coverageHoursNode) {
          coverageHoursNode.textContent = coverageHours.toFixed(1);
        }

        renderAnalyticsBarRows(volumeNode, volumeTrend, function (row) {
          return row.count;
        }, function (value) {
          return String(Math.round(value));
        });

        renderDeliveryBreakdown(deliveryNode, deliveryBreakdown);

        renderAnalyticsBarRows(latencyTrendNode, latencyTrend, function (row) {
          return row.p95_ms;
        }, function (value) {
          return String(Math.round(value)) + "ms";
        });
      })
      .catch(function () {
        if (statusNode) {
          statusNode.textContent = "Could not load analytics.";
        }
        if (insufficientNode) {
          insufficientNode.classList.remove("hide");
          insufficientNode.textContent = "Insufficient data: analytics are not available yet.";
        }
      });
  }

  if (window.dashboardBoot && window.dashboardBoot.autoRefresh) {
    refreshAnalyticsSummary();
    window.setInterval(function () {
      fetch("/api/health")
        .then(function (response) { return response.json(); })
        .then(function (health) {
          var healthError = document.querySelector("[data-health-error]");
          if (healthError) {
            healthError.textContent = health.last_error || "None";
          }
          var uptime = document.querySelector("[data-health-uptime]");
          if (uptime && typeof health.uptime_seconds === "number") {
            uptime.textContent = health.uptime_seconds + "s";
          }
        });
      fetch("/api/metrics")
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          document.querySelectorAll("[data-metric-counter]").forEach(function (node) {
            var key = node.getAttribute("data-metric-counter");
            node.textContent = (payload.counters || {})[key] || 0;
          });
          document.querySelectorAll("[data-metric-duration]").forEach(function (node) {
            var key = node.getAttribute("data-metric-duration");
            var value = (((payload.durations || {}).averages || {})[key]);
            node.textContent = typeof value === "number" ? value.toFixed(2) + "s" : "No data yet";
          });
        });
      refreshAnalyticsSummary();
    }, 30000);
  }

  var refreshButton = document.querySelector("[data-refresh-metrics]");
  if (refreshButton) {
    refreshButton.addEventListener("click", refreshMetrics);
  }
})();
