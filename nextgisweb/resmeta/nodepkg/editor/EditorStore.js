import { toJS, makeAutoObservable } from "mobx";

class Record {
    key;
    value;
    placeholder;

    constructor({ store, id, key, value, placeholder = false }) {
        makeAutoObservable(this);
        this.store = store;
        this.id = id;
        this.key = key;
        this.value = value;
        this.placeholder = placeholder;
    }

    get type() {
        const t = typeof this.value;
        if (t !== "undefined") {
            return t;
        }
    }

    get error() {
        if (this.key == "") {
            return "Key name is required.";
        }

        const duplicate = this.store.items.find(
            (candidate) => candidate.key == this.key && candidate.id != this.id
        );

        if (duplicate) {
            return "Key name is not unique.";
        }

        return false;
    }

    update({ key, value, type }) {
        if (key !== undefined) {
            this.key = key;
        }

        if (value !== undefined) {
            this.value = value;
        }

        if (type !== undefined) {
            if (type == "string") {
                if (this.value == undefined || this.value == null) {
                    this.value = "";
                } else {
                    this.value = this.value.toString();
                }
            } else if (type == "number") {
                try {
                    this.value = JSON.parse(this.value);
                } catch (e) {
                    this.value = 0;
                }
            }
        }

        this.placeholder = false;
        this.store.addPlaceholder();
    }
}

export class EditorStore {
    items = [];
    nextId = 0;

    constructor() {
        makeAutoObservable(this);
    }

    load(value) {
        this.items = Object.entries(value.items).map(
            ([key, value], id) => new Record({ store: this, id, key, value })
        );
        this.nextId = this.items.length;
        this.addPlaceholder();
    }

    dump() {
        const items = {};
        this.items.forEach((itm) => {
            items[itm.key] = itm.value;
        });
        return { items: toJS(items) };
    }

    delete(id) {
        this.items = this.items.filter((itm) => itm.id !== id);
        this.addPlaceholder();
    }

    addPlaceholder() {
        if (
            this.items.length == 0 ||
            !this.items[this.items.length - 1].placeholder
        ) {
            this.items.push(
                new Record({ store: this, id: this.nextId, placeholder: true })
            );
            this.nextId++;
        }
    }
}
