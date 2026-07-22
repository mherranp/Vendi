import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Native } from './native';

describe('Native', () => {
  let component: Native;
  let fixture: ComponentFixture<Native>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Native],
    }).compileComponents();

    fixture = TestBed.createComponent(Native);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
