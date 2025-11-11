class ResourceAvailabilityUpdater {
	constructor(options) {
		options = options || {};

		this.usages_json = options.usages_json;
		this.csrfmiddlewaretoken = options.csrfmiddlewaretoken;
		this.active_termin = null;
	}

	_render(data) {
		for (const [resource_id, bar_entries] of Object.entries(data.usage_bars)) {
			var bar = $("#usage_bar_" + resource_id);
			bar.empty();
			for (const [duration, kind, usage_ids] of bar_entries) {
				var classes = ["progress-bar"];
				if (kind == "direct" || kind == "super") {
					if (usage_ids.filter((usage_id) => data.usages[usage_id].termin_id == this.active_termin).length == 0) {
						classes.push("bg-primary");
					} else {
						classes.push("bg-danger");
					}
				} else if (kind == "part") {
					classes.push("bg-warning");
				} else if (kind == "free") {
					classes.push("bg-success");
				}
				// stripe progress bar if no usage is yet approved
				if (usage_ids.length > 0 && usage_ids.filter((usage_id) => data.usages[usage_id].approved).length == 0) {
					classes.push("progress-bar-striped");
				}
				var bar_part = $("<div>").addClass(classes).css("width", (duration / data.total * 100) + "%");
				bar_part.attr("title", usage_ids.map(function (usage_id) {
					var notes = [];
					if (data.usages[usage_id].resource_id != resource_id) {
						notes.push("für " + $("#resourceLabel_" + data.usages[usage_id].resource_id).text());
					}
					if (!data.usages[usage_id].approved) {
						notes.push("noch nicht bestätigt");
					}

					var label = data.usages[usage_id].termin_label;
					if (notes.length > 0) {
	                        		label = label + " (" + notes.join(", ") + ")";
					}
					return label;
				}).join("\n"))
				bar.append(bar_part);
			}
			bar.removeClass("d-none");
		}
	}

	update(start, end) {
		$(".usage_bar").toggleClass("d-none", true).empty();

		const timestamp_regex = /\d{4}-(0\d|1[0-2])-([0-2]\d|3[01])T([01]\d|2[0-3]):[0-5]\d$/;
		if (!timestamp_regex.test(start) || !timestamp_regex.test(end)) {
			return;
		}

		$.post(
			this.usages_json,
			{"csrfmiddlewaretoken": this.csrfmiddlewaretoken,
			 "start": start,
			 "end": end},
			this._render.bind(this),
		);
	}
}
