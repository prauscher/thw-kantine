function multiplechoicefragewidget_replaceIndex(elem, search, replace) {
	var $ = django.jQuery || jQuery;

	if ($(elem).prop("for")) {
		$(elem).prop("for", $(elem).prop("for").replace(search, replace));
	}
	if (elem.id) {
		elem.id = elem.id.replace(search, replace);
	}
	if (elem.name) {
		elem.name = elem.name.replace(search, replace);
	}
}

function multiplechoicefragewidget_checkFragen(field) {
	var $ = django.jQuery || jQuery;

	var fragen_container = $(field).parents(".fragen_container");
	if (fragen_container.find(".frage_text:visible textarea").filter((i, elem) => elem.value == "").length == 0) {
		var template = $(fragen_container.find(".frage_container:hidden")[0]);
		const next_id = fragen_container.find(".frage_container:visible").length;
		var cloned = template.clone(true);
		cloned.find(".frage_sort").val(fragen_container.find(".frage_sort").map((i, elem) => Number(elem.value)).toArray().reduce((acc, cur) => Math.max(acc, cur), 0) + 10);
		cloned.find("*").each(function () {multiplechoicefragewidget_replaceIndex(this, "__frage_template__", next_id);});
		cloned.show();
		cloned.insertBefore(template);
		fragen_container.find(".fragen_count").val(next_id + 1);
		// Reenable markdownx...
		cloned[0].dispatchEvent(new CustomEvent("formset:added", {bubbles: true}));
	}
}

function multiplechoicefragewidget_checkAntworten(field) {
	var $ = django.jQuery || jQuery;

	var antworten_container = $(field).parents(".frage_container");
	if (antworten_container.find(".antwort_text:visible textarea").filter((i, elem) => elem.value == "").length == 0) {
		var template = $(antworten_container.find(".antwort_container:hidden")[0]);
		const next_id = antworten_container.find(".antwort_container:visible").length;
		var cloned = template.clone(true);
		cloned.find("*").each(function () {multiplechoicefragewidget_replaceIndex(this, "__antwort_template__", next_id);});
		cloned.show();
		cloned.insertBefore(template);
		antworten_container.find(".antworten_count").val(next_id + 1);
		// Reenable markdownx...
		cloned[0].dispatchEvent(new CustomEvent("formset:added", {bubbles: true}));
	}
}
