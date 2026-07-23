import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/** Raíz de `vendi-admin`. Solo hospeda el enrutador. */
@Component({
  selector: 'vd-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {}
