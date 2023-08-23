import orderBy from "lodash/orderBy";
import reactApp from "@nextgisweb/gui/react-app";

import NavigationMenu from "@nextgisweb/webmap/navigation-menu";

import type { DojoDisplay, DojoItem, PanelDojoItem } from "./type";

interface PanelElements {
    main: DojoItem;
    leftPanel: PanelDojoItem;
    navigation: HTMLElement;
}

class Deferred<T> {
    promise: Promise<T>;
    resolve!: (value: T | PromiseLike<T>) => void;
    reject!: (reason: unknown) => void;

    constructor() {
        this.promise = new Promise<T>((resolve, reject) => {
            this.resolve = resolve;
            this.reject = reject;
        });
    }
}

function isFuncReactComponent(cls: any): cls is React.FC {
    return (
        typeof cls === "function" &&
        String(cls).includes("return React.createElement")
    );
}

export class PanelsManager {
    private _display: DojoDisplay;
    private _domElements!: PanelElements;
    private _activePanelKey?: string;
    private _panels = new Map<string, PanelDojoItem>();
    private _initialized = false;
    private _initPromises: Promise<PanelDojoItem>[] = [];

    private _onChangePanel: (panel?: PanelDojoItem) => void;
    private _panelsReady = new Deferred<void>();

    constructor(
        display: DojoDisplay,
        activePanelKey: string | undefined,
        onChangePanel: (panel?: PanelDojoItem) => void
    ) {
        this._display = display;
        this._activePanelKey = activePanelKey;
        this._onChangePanel = onChangePanel;
    }

    private _clickNavigationMenu(newPanel: PanelDojoItem): void {
        const { name } = newPanel;

        if (this._activePanelKey === name) {
            this._deactivatePanel(newPanel);
            this._activePanelKey = undefined;
        } else {
            if (this._activePanelKey) {
                const activePanel = this._panels.get(this._activePanelKey);
                if (activePanel) {
                    this._deactivatePanel(activePanel);
                }
            }
            this._activatePanel(newPanel);
            this._activePanelKey = name;
        }

        this._buildNavigationMenu();
    }

    private _buildNavigationMenu(): void {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        reactApp<any>(
            NavigationMenu,
            {
                panels: this._panels,
                active: this._activePanelKey,
                onClick: (p: PanelDojoItem) => this._clickNavigationMenu(p),
            },
            this._domElements.navigation
        );
    }

    private _activatePanel(panel: PanelDojoItem): void {
        if (panel.isFullWidth) {
            this._domElements.leftPanel.domNode.classList.add(
                "leftPanelPane--fullwidth"
            );
            this._domElements.leftPanel.set("splitter", false);
        }

        this._domElements.leftPanel.addChild(panel);
        this._domElements.main.addChild(this._domElements.leftPanel);

        panel.show && panel.show(); // DynamicPanel
        panel.set("isOpen", true); // React panel wrapper
        this._onChangePanel(panel);
    }

    private _deactivatePanel(panel: PanelDojoItem): void {
        this._domElements.main.removeChild(this._domElements.leftPanel);
        this._domElements.leftPanel.removeChild(panel);

        if (panel.isFullWidth) {
            this._domElements.leftPanel.domNode.classList.remove(
                "leftPanelPane--fullwidth"
            );
            this._domElements.leftPanel.set("splitter", true);
        }

        panel.hide && panel.hide(); // DynamicPanel
        panel.set("isOpen", false); // React panel wrapper
        this._onChangePanel(undefined);
    }

    private _closePanel(panel: PanelDojoItem): void {
        this._deactivatePanel(panel);
        this._activePanelKey = undefined;
    }

    private _handleInitActive(): void {
        if (this._initialized) {
            return;
        }

        if (this._activePanelKey === "none") {
            this._activePanelKey = undefined;
            this._initialized = true;
            this._panelsReady.resolve();
        }

        if (this._activePanelKey && this._panels.has(this._activePanelKey)) {
            const activePanel = this._panels.get(this._activePanelKey);
            if (activePanel) {
                this._activatePanel(activePanel);
                this._initialized = true;
                this._panelsReady.resolve();
            }
        }
    }

    private _activateFirstPanel(): void {
        const [name, firstPanel] = this._panels.entries().next().value;
        this._activePanelKey = name;
        this._activatePanel(firstPanel);
    }

    private _makePanel(panel: PanelDojoItem): void {
        if (!panel) {
            return;
        }

        let newPanel: PanelDojoItem;
        let name: string;
        if (panel.cls) {
            const { cls, params } = panel;
            name = params.name;

            if (isFuncReactComponent(cls)) {
                throw new Error("Panel React rendering is not implemented");
            } else {
                const widget = new cls({ ...params, display: this._display });
                if (widget.on) {
                    widget.on("closed", (panel: PanelDojoItem) => {
                        // can't reach this event
                        this._closePanel(panel);
                    });
                }
                newPanel = widget;
            }
        } else {
            name = panel.name;
            if (panel.on) {
                panel.on("closed", (panel: PanelDojoItem) => {
                    // can't reach this event
                    this._closePanel(panel);
                });
            }
            newPanel = panel;
        }

        if (this._panels.has(name)) {
            console.error(`Panel ${name} was alredy added`);
            return;
        }

        const existingPanels = Array.from(this._panels.values());
        let newPanels = [...existingPanels, newPanel];
        newPanels = orderBy(newPanels, "order", "asc");
        this._panels = new Map(newPanels.map((p) => [p.name, p]));
        this._buildNavigationMenu();
        this._handleInitActive();
    }

    initDomElements(domElements: PanelElements): void {
        const { main, leftPanel, navigation } = domElements;
        this._domElements = { main, leftPanel, navigation };
        this._buildNavigationMenu();
    }

    initFinalize(): void {
        Promise.all(this._initPromises).then(() => {
            this._handleInitActive();
            if (!this._initialized) {
                this._activateFirstPanel();
                this._panelsReady.resolve();
                this._initialized = true;
            }
            this._initPromises.length = 0;
        });
    }

    async addPanels(
        panelsInfo: PanelDojoItem[] | PanelDojoItem | Promise<PanelDojoItem>[]
    ): Promise<void> {
        const panels: (PanelDojoItem | Promise<PanelDojoItem>)[] =
            Array.isArray(panelsInfo) ? panelsInfo : [panelsInfo];
        const promises = panels.filter(
            (p): p is Promise<PanelDojoItem> => p instanceof Promise
        );

        promises.forEach((p) =>
            p.then((panelInfo) => {
                this._makePanel(panelInfo);
            })
        );

        if (!this._initialized) {
            this._initPromises.push(...promises);
        }

        const readyPanels = panels.filter(
            (p): p is PanelDojoItem => !(p instanceof Promise)
        );
        readyPanels.forEach((panelInfo) => {
            this._makePanel(panelInfo);
        });
    }

    getPanel(name: string): PanelDojoItem | undefined {
        return this._panels.get(name);
    }

    get panelsReady(): Deferred<void> {
        return this._panelsReady;
    }
}
